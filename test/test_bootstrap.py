"""Tests for admin bootstrap process.

These tests verify that the bootstrap process correctly creates admin tokens
and that admin tokens have the necessary permissions to manage sources and groups.
"""

import pytest
from gofr_common.auth.service import AuthService
from app.services import (
    AdminAccessDeniedError,
    SourceRegistry,
    init_group_service,
    is_admin,
    require_admin,
)
from app.models import SourceType, TrustLevel


ADMIN_GROUP = "admin"


class TestAdminBootstrap:
    """Test admin token bootstrap and verification."""

    def test_admin_token_has_admin_group(self, vault_auth_service: AuthService):
        """Admin token contains admin group membership."""
        # Create admin token
        admin_token = vault_auth_service.create_token(groups=[ADMIN_GROUP])
        
        # Verify token is not empty
        assert admin_token
        assert len(admin_token) > 20
        
        # Verify token contains admin group (via is_admin check)
        init_group_service(auth_service=vault_auth_service)
        assert is_admin(auth_tokens=[admin_token]) is True

    def test_admin_token_can_be_verified(self, vault_auth_service: AuthService):
        """Admin token passes require_admin check."""
        init_group_service(auth_service=vault_auth_service)
        
        # Create admin token
        admin_token = vault_auth_service.create_token(groups=[ADMIN_GROUP])
        
        # Should not raise exception
        try:
            require_admin(auth_tokens=[admin_token])
        except AdminAccessDeniedError:
            pytest.fail("Admin token should pass require_admin check")

    def test_non_admin_token_fails_admin_check(self, vault_auth_service: AuthService):
        """Non-admin token fails require_admin check."""
        init_group_service(auth_service=vault_auth_service)
        
        # Create non-admin token (use existing test group)
        user_token = vault_auth_service.create_token(groups=["test-group"])
        
        # Should raise AdminAccessDeniedError
        with pytest.raises(AdminAccessDeniedError) as exc_info:
            require_admin(auth_tokens=[user_token])
        
        assert "admin" in str(exc_info.value).lower()


class TestAdminSourceManagement:
    """Test that admin tokens can manage sources."""

    def test_admin_can_create_source(
        self,
        vault_auth_service: AuthService,
        tmp_path,
    ):
        """Admin token can create sources."""
        init_group_service(auth_service=vault_auth_service)
        
        # Create admin token
        admin_token = vault_auth_service.create_token(groups=[ADMIN_GROUP])
        
        # Create source registry
        source_registry = SourceRegistry(base_path=tmp_path / "sources")
        
        # Verify admin can pass the require_admin check
        require_admin(auth_tokens=[admin_token])
        
        # Create source (no group_guid needed)
        source = source_registry.create(
            name="Test Source",
            source_type=SourceType.NEWS_AGENCY,
            trust_level=TrustLevel.HIGH,
        )
        
        assert source.source_guid
        assert source.name == "Test Source"

    def test_non_admin_fails_admin_check_for_sources(
        self,
        vault_auth_service: AuthService,
    ):
        """Non-admin token cannot pass admin check for source management."""
        init_group_service(auth_service=vault_auth_service)
        
        # Create non-admin token (use existing test group)
        user_token = vault_auth_service.create_token(groups=["test-group"])
        
        # Should fail admin check
        with pytest.raises(AdminAccessDeniedError):
            require_admin(auth_tokens=[user_token])


class TestAnonymousAccess:
    """Test that anonymous users cannot perform admin operations."""

    def test_anonymous_user_is_not_admin(self, vault_auth_service: AuthService):
        """Anonymous user (no token) is not admin."""
        init_group_service(auth_service=vault_auth_service)
        
        # No token = not admin
        assert is_admin(auth_tokens=None) is False
        assert is_admin(auth_tokens=[]) is False

    def test_anonymous_user_fails_admin_check(self, vault_auth_service: AuthService):
        """Anonymous user fails require_admin check."""
        init_group_service(auth_service=vault_auth_service)
        
        # Should raise AdminAccessDeniedError
        with pytest.raises(AdminAccessDeniedError):
            require_admin(auth_tokens=None)


class TestMultipleGroups:
    """Test admin access with multiple group memberships."""

    def test_admin_with_multiple_groups_is_admin(self, vault_auth_service: AuthService):
        """Token with admin + other groups is still admin."""
        init_group_service(auth_service=vault_auth_service)
        
        # Create token with admin + other groups (use existing test groups)
        token = vault_auth_service.create_token(groups=[ADMIN_GROUP, "test-group", "reader-group"])
        
        # Should be recognized as admin
        assert is_admin(auth_tokens=[token]) is True

    def test_user_with_multiple_non_admin_groups_is_not_admin(self, vault_auth_service: AuthService):
        """Token with multiple non-admin groups is not admin."""
        init_group_service(auth_service=vault_auth_service)
        
        # Create token without admin (use existing test groups)
        token = vault_auth_service.create_token(groups=["test-group", "reader-group", "writer-group"])
        
        # Should not be admin
        assert is_admin(auth_tokens=[token]) is False
