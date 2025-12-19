"""Tests for Group Access Control - Phase 4.

Tests for JWT token group extraction, membership validation,
and permission checking. Updated for auth v2 multi-group tokens.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from gofr_common.auth import AuthService

from app.auth import (
    AccessDeniedError,
    AccessLevel,
    GroupAccessService,
    GroupClaims,
    GroupNotFoundError,
    TokenValidationError,
)
from gofr_common.auth.exceptions import TokenError, TokenExpiredError
from app.models import Permission


# =============================================================================
# Test Fixtures
# =============================================================================

# NOTE: auth_service fixture is provided by conftest.py using Vault backend
# All groups are pre-created in vault_auth_service fixture


@pytest.fixture
def group_store() -> dict:
    """Create a sample group store for testing."""
    return {
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": {
            "name": "APAC Research",
            "tokens": {
                "admin-group": [Permission.READ, Permission.CREATE, Permission.UPDATE, Permission.DELETE],
                "writer-group": [Permission.READ, Permission.CREATE, Permission.UPDATE],
                "reader-group": [Permission.READ],
            },
        },
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb": {
            "name": "EMEA Research",
            "tokens": {
                "emea-reader": [Permission.READ],
            },
        },
    }


@pytest.fixture
def access_service(auth_service: AuthService, group_store: dict) -> GroupAccessService:
    """Create a group access service with test configuration."""
    return GroupAccessService(auth_service=auth_service, group_store=group_store)


# =============================================================================
# Phase 4.1: Extract Groups from Token
# =============================================================================


class TestExtractGroupsFromToken:
    """Tests for extracting group claims from JWT tokens."""

    def test_extract_groups_from_token(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test extracting groups from a valid token."""
        # Create a token for a group
        token = auth_service.create_token(groups=["admin-group"])

        claims = access_service.extract_groups_from_token(token)

        assert isinstance(claims, GroupClaims)
        assert claims.primary_group == "admin-group"
        assert "admin-group" in claims.groups
        assert isinstance(claims.issued_at, datetime)
        assert isinstance(claims.expires_at, datetime)
        assert claims.expires_at > claims.issued_at

    def test_extract_groups_from_invalid_token(
        self, access_service: GroupAccessService
    ) -> None:
        """Test that invalid tokens raise TokenError."""
        with pytest.raises(TokenError):
            access_service.extract_groups_from_token("invalid-token")

    def test_extract_groups_from_expired_token(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test that expired tokens raise TokenExpiredError."""
        # Create a token that's already expired
        token = auth_service.create_token(
            groups=["admin-group"],
            expires_in_seconds=-1,  # Already expired
        )

        with pytest.raises(TokenExpiredError) as exc_info:
            access_service.extract_groups_from_token(token)

        assert "expired" in str(exc_info.value).lower()

    def test_group_claims_has_group(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test GroupClaims.has_group method."""
        token = auth_service.create_token(groups=["test-group"])
        claims = access_service.extract_groups_from_token(token)

        assert claims.has_group("test-group") is True
        assert claims.has_group("other-group") is False


# =============================================================================
# Phase 4.2: Group Membership Validation
# =============================================================================


class TestValidateGroupMembership:
    """Tests for validating group membership."""

    def test_validate_group_membership(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test validating membership in a group the token has access to."""
        token = auth_service.create_token(groups=["admin-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        claims = access_service.validate_group_membership(token, group_guid=group_guid)

        assert claims.primary_group == "admin-group"

    def test_validate_group_membership_denied(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test that membership validation fails for inaccessible groups."""
        # Create token for a group that has no access to EMEA
        token = auth_service.create_token(groups=["admin-group"])
        emea_group = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        # admin-group is not in EMEA's tokens, so should fail
        with pytest.raises(AccessDeniedError) as exc_info:
            access_service.validate_group_membership(token, group_guid=emea_group)

        assert emea_group in str(exc_info.value)

    def test_validate_membership_invalid_token(
        self, access_service: GroupAccessService
    ) -> None:
        """Test membership validation with invalid token."""
        with pytest.raises(TokenError):
            access_service.validate_group_membership(
                "invalid", group_guid="any-group"
            )


# =============================================================================
# Phase 4.3: Permission Check
# =============================================================================


class TestPermissionCheck:
    """Tests for permission checking."""

    def test_permission_check_read(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test checking read permission."""
        token = auth_service.create_token(groups=["reader-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        claims = access_service.check_permission(
            token, group_guid, Permission.READ
        )

        assert claims.primary_group == "reader-group"

    def test_permission_check_write_denied(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test that write permission is denied for read-only token."""
        token = auth_service.create_token(groups=["reader-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        with pytest.raises(AccessDeniedError) as exc_info:
            access_service.check_permission(
                token, group_guid, Permission.CREATE
            )

        assert exc_info.value.required_permission == Permission.CREATE

    def test_permission_check_admin(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test checking all permissions for admin token."""
        token = auth_service.create_token(groups=["admin-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        # Admin should have all permissions
        for permission in Permission:
            claims = access_service.check_permission(
                token, group_guid, permission
            )
            assert claims is not None

    def test_permission_check_group_not_found(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test permission check for non-existent group."""
        token = auth_service.create_token(groups=["unknown-group"])

        with pytest.raises(AccessDeniedError):
            # Token doesn't have access to this group
            access_service.check_permission(
                token,
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                Permission.READ,
            )

    def test_access_level_read(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test checking READ access level."""
        token = auth_service.create_token(groups=["reader-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        claims = access_service.check_access_level(
            token, group_guid, AccessLevel.READ
        )

        assert claims is not None

    def test_access_level_write_requires_multiple_permissions(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test that WRITE access level requires multiple permissions."""
        # Reader only has READ permission
        token = auth_service.create_token(groups=["reader-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        with pytest.raises(AccessDeniedError) as exc_info:
            access_service.check_access_level(
                token, group_guid, AccessLevel.WRITE
            )

        assert "Missing permissions" in str(exc_info.value)

    def test_access_level_write_granted(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test WRITE access level with proper permissions."""
        token = auth_service.create_token(groups=["writer-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        claims = access_service.check_access_level(
            token, group_guid, AccessLevel.WRITE
        )

        assert claims is not None

    def test_access_level_admin(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test ADMIN access level."""
        token = auth_service.create_token(groups=["admin-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        claims = access_service.check_access_level(
            token, group_guid, AccessLevel.ADMIN
        )

        assert claims is not None


# =============================================================================
# Phase 4.4: Integration with Document Store
# =============================================================================


class TestDocumentAccessByGroup:
    """Tests for document access control by group."""

    def test_document_access_by_group(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test accessing a document requires group membership."""
        # User with access to group A
        token = auth_service.create_token(groups=["admin-group"])
        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        # Should succeed for group A
        claims = access_service.validate_group_membership(token, group_a)
        assert claims.has_group("admin-group")

    def test_document_access_denied_wrong_group(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test that document access is denied for wrong group."""
        # User with access to admin-group
        token = auth_service.create_token(groups=["admin-group"])
        group_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        # Should fail for group B (token is for admin-group, not emea-reader)
        with pytest.raises(AccessDeniedError):
            access_service.validate_group_membership(token, group_b)

    def test_get_accessible_groups(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test getting list of accessible groups for a token."""
        token = auth_service.create_token(groups=["admin-group"])

        groups = access_service.get_accessible_groups(token)

        assert "admin-group" in groups
        assert len(groups) >= 1

    def test_read_permission_for_documents(
        self, auth_service: AuthService, access_service: GroupAccessService
    ) -> None:
        """Test read permission check for document access."""
        token = auth_service.create_token(groups=["reader-group"])
        group_guid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        # Reader should be able to read
        claims = access_service.check_permission(
            token, group_guid, Permission.READ
        )
        assert claims is not None

        # Reader should not be able to create
        with pytest.raises(AccessDeniedError):
            access_service.check_permission(
                token, group_guid, Permission.CREATE
            )

    def test_no_group_store_allows_all(
        self, auth_service: AuthService
    ) -> None:
        """Test that without group_store, all permissions are granted."""
        # Service without group store (admin/testing mode)
        service = GroupAccessService(auth_service=auth_service)
        token = auth_service.create_token(groups=["any-group"])

        # Should succeed without group store restrictions
        claims = service.check_permission(
            token, "any-group", Permission.DELETE
        )
        assert claims is not None


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_access_denied_error_attributes(self) -> None:
        """Test AccessDeniedError contains proper attributes."""
        error = AccessDeniedError(
            group_guid="test-group",
            required_permission=Permission.READ,
            reason="Test reason",
        )

        assert error.group_guid == "test-group"
        assert error.required_permission == Permission.READ
        assert error.reason == "Test reason"
        assert "test-group" in str(error)
        assert "read" in str(error)

    def test_token_validation_error(self) -> None:
        """Test TokenValidationError message."""
        error = TokenValidationError("Invalid signature")

        assert "Invalid signature" in str(error)
        assert error.reason == "Invalid signature"

    def test_group_not_found_error(self) -> None:
        """Test GroupNotFoundError attributes."""
        error = GroupNotFoundError("test-guid")

        # gofr_common's GroupNotFoundError is a simple exception
        assert "test-guid" in str(error)

    def test_access_level_required_permissions(self) -> None:
        """Test AccessLevel permission mappings."""
        assert Permission.READ in AccessLevel.READ.required_permissions
        assert len(AccessLevel.READ.required_permissions) == 1

        assert Permission.READ in AccessLevel.WRITE.required_permissions
        assert Permission.CREATE in AccessLevel.WRITE.required_permissions
        assert Permission.UPDATE in AccessLevel.WRITE.required_permissions

        assert len(AccessLevel.ADMIN.required_permissions) == 4
        for perm in Permission:
            assert perm in AccessLevel.ADMIN.required_permissions
