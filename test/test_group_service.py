"""Tests for GroupService with gofr_common.auth v2 multi-group tokens."""

import pytest


from app.services.group_service import (
    AdminAccessDeniedError,
    GroupService,
    GroupAccessDeniedError,
    PUBLIC_GROUP,
    extract_group,
    get_permitted_groups,
    init_group_service,
    get_group_service,
    is_admin,
    require_admin,
    resolve_permitted_groups,
)


# NOTE: auth_service fixture is provided by conftest.py using Vault backend
# All groups are pre-created in vault_auth_service fixture


def _ensure_group(auth_service, group_id: str, name: str | None = None) -> None:
    """Create group if it doesn't exist (idempotent)."""
    try:
        auth_service.groups.create_group(group_id, name if name else group_id)
    except Exception:
        pass  # Group may already exist - that's fine


@pytest.fixture
def group_service(auth_service):
    """Create a GroupService with auth service."""
    return GroupService(auth_service=auth_service)


class TestGroupServiceExtractGroup:
    """Test GroupService.extract_group with multi-group tokens."""

    def test_extract_group_returns_primary_group(self, auth_service, group_service):
        """Primary group is the first group in the token."""
        # Create group first
        _ensure_group(auth_service, "primary-group")
        _ensure_group(auth_service, "secondary-group")
        
        token = auth_service.create_token(groups=["primary-group", "secondary-group"])
        token_info = auth_service.verify_token(token)
        
        result = group_service.extract_group(token_info)
        assert result == "primary-group"

    def test_extract_group_single_group(self, auth_service, group_service):
        """Single group token returns that group."""
        _ensure_group(auth_service, "only-group")
        token = auth_service.create_token(groups=["only-group"])
        token_info = auth_service.verify_token(token)
        
        result = group_service.extract_group(token_info)
        assert result == "only-group"

    def test_extract_group_none_returns_public(self, group_service):
        """None token_info returns public group."""
        result = group_service.extract_group(None)
        assert result == PUBLIC_GROUP

    def test_extract_group_convenience_function(self, auth_service):
        """Module-level extract_group function works."""
        _ensure_group(auth_service, "test-group")
        token = auth_service.create_token(groups=["test-group"])
        token_info = auth_service.verify_token(token)
        
        result = extract_group(token_info)
        assert result == "test-group"

    def test_extract_group_convenience_none(self):
        """Module-level extract_group returns public for None."""
        result = extract_group(None)
        assert result == PUBLIC_GROUP


class TestGroupServiceGetPermittedGroups:
    """Test GroupService.get_permitted_groups with multi-group tokens."""

    def test_permitted_groups_includes_all_token_groups(self, auth_service, group_service):
        """All groups from token are permitted."""
        _ensure_group(auth_service, "group-a")
        _ensure_group(auth_service, "group-b")
        _ensure_group(auth_service, "group-c")
        
        token = auth_service.create_token(groups=["group-a", "group-b", "group-c"])
        token_info = auth_service.verify_token(token)
        
        result = group_service.get_permitted_groups(token_info)
        assert set(result) == {"public", "group-a", "group-b", "group-c"}

    def test_permitted_groups_always_includes_public(self, auth_service, group_service):
        """Public is always in permitted groups."""
        _ensure_group(auth_service, "private-group")
        token = auth_service.create_token(groups=["private-group"])
        token_info = auth_service.verify_token(token)
        
        result = group_service.get_permitted_groups(token_info)
        assert PUBLIC_GROUP in result

    def test_permitted_groups_none_returns_only_public(self, group_service):
        """None token_info returns only public."""
        result = group_service.get_permitted_groups(None)
        assert result == [PUBLIC_GROUP]

    def test_permitted_groups_convenience_function(self, auth_service):
        """Module-level get_permitted_groups function works."""
        _ensure_group(auth_service, "my-group")
        token = auth_service.create_token(groups=["my-group"])
        token_info = auth_service.verify_token(token)
        
        result = get_permitted_groups(token_info)
        assert set(result) == {"public", "my-group"}


class TestGroupServiceWriteAccess:
    """Test GroupService write access methods."""

    def test_get_write_group_returns_primary(self, auth_service, group_service):
        """get_write_group returns the primary (first) group."""
        _ensure_group(auth_service, "write-group")
        _ensure_group(auth_service, "other-group")
        
        token = auth_service.create_token(groups=["write-group", "other-group"])
        token_info = auth_service.verify_token(token)
        
        result = group_service.get_write_group(token_info)
        assert result == "write-group"

    def test_get_write_group_none_returns_none(self, group_service):
        """get_write_group returns None for unauthenticated."""
        result = group_service.get_write_group(None)
        assert result is None

    def test_get_write_groups_returns_all(self, auth_service, group_service):
        """get_write_groups returns all token groups."""
        _ensure_group(auth_service, "group-x")
        _ensure_group(auth_service, "group-y")
        
        token = auth_service.create_token(groups=["group-x", "group-y"])
        token_info = auth_service.verify_token(token)
        
        result = group_service.get_write_groups(token_info)
        assert set(result) == {"group-x", "group-y"}

    def test_get_write_groups_none_returns_empty(self, group_service):
        """get_write_groups returns empty list for unauthenticated."""
        result = group_service.get_write_groups(None)
        assert result == []


class TestGroupServiceValidation:
    """Test GroupService access validation."""

    def test_validate_read_access_own_group(self, auth_service, group_service):
        """User can read from their own groups."""
        _ensure_group(auth_service, "my-group")
        token = auth_service.create_token(groups=["my-group"])
        token_info = auth_service.verify_token(token)
        
        assert group_service.validate_read_access(token_info, "my-group") is True

    def test_validate_read_access_public(self, auth_service, group_service):
        """User can always read from public."""
        _ensure_group(auth_service, "some-group")
        token = auth_service.create_token(groups=["some-group"])
        token_info = auth_service.verify_token(token)
        
        assert group_service.validate_read_access(token_info, PUBLIC_GROUP) is True

    def test_validate_read_access_other_group_denied(self, auth_service, group_service):
        """User cannot read from groups they don't have."""
        _ensure_group(auth_service, "my-group")
        _ensure_group(auth_service, "other-group")
        
        token = auth_service.create_token(groups=["my-group"])
        token_info = auth_service.verify_token(token)
        
        assert group_service.validate_read_access(token_info, "other-group") is False

    def test_validate_read_access_anonymous_public_only(self, group_service):
        """Anonymous users can only read public."""
        assert group_service.validate_read_access(None, PUBLIC_GROUP) is True
        assert group_service.validate_read_access(None, "private-group") is False

    def test_validate_write_access_own_group(self, auth_service, group_service):
        """User can write to any of their groups."""
        _ensure_group(auth_service, "group-1")
        _ensure_group(auth_service, "group-2")
        
        token = auth_service.create_token(groups=["group-1", "group-2"])
        token_info = auth_service.verify_token(token)
        
        assert group_service.validate_write_access(token_info, "group-1") is True
        assert group_service.validate_write_access(token_info, "group-2") is True

    def test_validate_write_access_other_group_denied(self, auth_service, group_service):
        """User cannot write to groups they don't have."""
        _ensure_group(auth_service, "my-group")
        _ensure_group(auth_service, "not-my-group")
        
        token = auth_service.create_token(groups=["my-group"])
        token_info = auth_service.verify_token(token)
        
        assert group_service.validate_write_access(token_info, "not-my-group") is False

    def test_validate_write_access_anonymous_denied(self, group_service):
        """Anonymous users cannot write to anything."""
        assert group_service.validate_write_access(None, PUBLIC_GROUP) is False
        assert group_service.validate_write_access(None, "any-group") is False


class TestGroupServiceSingleton:
    """Test GroupService singleton pattern."""

    def test_init_and_get_group_service(self, auth_service):
        """init_group_service and get_group_service work."""
        service = init_group_service(auth_service)
        
        retrieved = get_group_service()
        assert retrieved is service
        assert retrieved.auth_service is auth_service

    def test_get_group_service_not_initialized_raises(self):
        """get_group_service raises if not initialized."""
        # Reset singleton
        import app.services.group_service as gs
        gs._group_service = None
        
        with pytest.raises(RuntimeError, match="not initialized"):
            get_group_service()


class TestGroupServicePublicGroup:
    """Test public group behavior."""

    def test_is_public_group(self, group_service):
        """is_public_group correctly identifies public."""
        assert group_service.is_public_group(PUBLIC_GROUP) is True
        assert group_service.is_public_group("public") is True
        assert group_service.is_public_group("other") is False

    def test_public_group_constant_matches_reserved(self):
        """PUBLIC_GROUP constant matches gofr_common reserved group."""
        from gofr_common.auth import RESERVED_GROUPS
        assert PUBLIC_GROUP in RESERVED_GROUPS


class TestGroupAccessDeniedError:
    """Test GroupAccessDeniedError exception."""

    def test_error_message(self):
        """Error has expected message format."""
        error = GroupAccessDeniedError("secret-group")
        assert "secret-group" in str(error)

    def test_error_with_permitted_groups(self):
        """Error includes permitted groups in message."""
        error = GroupAccessDeniedError(
            "secret-group",
            permitted_groups=["public", "user-group"]
        )
        assert "secret-group" in str(error)
        assert "permitted" in str(error)

    def test_error_attributes(self):
        """Error has expected attributes."""
        error = GroupAccessDeniedError(
            "target-group",
            permitted_groups=["a", "b"],
            message="Custom message"
        )
        assert error.group_guid == "target-group"
        assert error.permitted_groups == ["a", "b"]


class TestResolvePermittedGroups:
    """Test resolve_permitted_groups with explicit tokens.
    
    This function is the key to supporting MCPO proxy which doesn't
    forward Authorization headers. Tests pass JWT tokens explicitly.
    """

    def test_explicit_single_token(self, auth_service):
        """Single explicit token extracts groups correctly."""
        _ensure_group(auth_service, "explicit-group")
        
        # Initialize group service so resolve_permitted_groups can find auth_service
        init_group_service(auth_service)
        
        token = auth_service.create_token(groups=["explicit-group"])
        
        result = resolve_permitted_groups(auth_tokens=[token])
        assert set(result) == {"public", "explicit-group"}

    def test_explicit_multi_token(self, auth_service):
        """Multiple explicit tokens union their groups."""
        _ensure_group(auth_service, "group-alpha")
        _ensure_group(auth_service, "group-beta")
        _ensure_group(auth_service, "group-gamma")
        
        init_group_service(auth_service)
        
        token1 = auth_service.create_token(groups=["group-alpha"])
        token2 = auth_service.create_token(groups=["group-beta", "group-gamma"])
        
        result = resolve_permitted_groups(auth_tokens=[token1, token2])
        assert set(result) == {"public", "group-alpha", "group-beta", "group-gamma"}

    def test_explicit_token_with_auth_service_param(self, auth_service):
        """Can pass auth_service explicitly instead of using global."""
        _ensure_group(auth_service, "param-group")
        
        token = auth_service.create_token(groups=["param-group"])
        
        # Don't init global, pass auth_service directly
        result = resolve_permitted_groups(
            auth_tokens=[token],
            auth_service=auth_service
        )
        assert set(result) == {"public", "param-group"}

    def test_explicit_token_strips_bearer_prefix(self, auth_service):
        """Tokens with "Bearer " prefix are handled correctly."""
        _ensure_group(auth_service, "bearer-group")
        
        init_group_service(auth_service)
        
        token = auth_service.create_token(groups=["bearer-group"])
        token_with_bearer = f"Bearer {token}"
        
        result = resolve_permitted_groups(auth_tokens=[token_with_bearer])
        assert set(result) == {"public", "bearer-group"}

    def test_explicit_empty_list_falls_back_to_context(self, auth_service):
        """Empty token list falls back to context (returns public)."""
        init_group_service(auth_service)
        
        # Empty list should fall back to context, which has no header = public
        result = resolve_permitted_groups(auth_tokens=[])
        assert result == [PUBLIC_GROUP]

    def test_explicit_none_falls_back_to_context(self, auth_service):
        """None auth_tokens falls back to context (returns public)."""
        init_group_service(auth_service)
        
        # None should fall back to context, which has no header = public
        result = resolve_permitted_groups(auth_tokens=None)
        assert result == [PUBLIC_GROUP]

    def test_explicit_invalid_token_returns_public(self, auth_service):
        """Invalid tokens result in public-only access."""
        init_group_service(auth_service)
        
        result = resolve_permitted_groups(auth_tokens=["invalid-garbage-token"])
        assert result == [PUBLIC_GROUP]

    def test_explicit_mixed_valid_invalid_tokens(self, auth_service):
        """Mixed valid/invalid tokens: valid ones contribute groups."""
        _ensure_group(auth_service, "valid-group")
        
        init_group_service(auth_service)
        
        valid_token = auth_service.create_token(groups=["valid-group"])
        
        result = resolve_permitted_groups(
            auth_tokens=[valid_token, "invalid-token", "another-bad-one"]
        )
        # Valid token's group + public (invalid tokens ignored)
        assert set(result) == {"public", "valid-group"}

    def test_explicit_always_includes_public(self, auth_service):
        """Result always includes public group."""
        _ensure_group(auth_service, "private-only")
        
        init_group_service(auth_service)
        
        token = auth_service.create_token(groups=["private-only"])
        
        result = resolve_permitted_groups(auth_tokens=[token])
        assert PUBLIC_GROUP in result


# =============================================================================
# Admin Access Control Tests
# =============================================================================


class TestIsAdmin:
    """Test is_admin() function."""

    def test_is_admin_with_admin_group(self, auth_service):
        """Token with admin group returns True."""
        init_group_service(auth_service)
        
        # Admin is a reserved group, should already exist
        admin_token = auth_service.create_token(groups=["admin"])
        
        result = is_admin(auth_tokens=[admin_token], auth_service=auth_service)
        assert result is True

    def test_is_admin_without_admin_group(self, auth_service):
        """Token without admin group returns False."""
        _ensure_group(auth_service, "regular-user")
        init_group_service(auth_service)
        
        user_token = auth_service.create_token(groups=["regular-user"])
        
        result = is_admin(auth_tokens=[user_token], auth_service=auth_service)
        assert result is False

    def test_is_admin_with_multiple_groups_including_admin(self, auth_service):
        """Token with admin among multiple groups returns True."""
        _ensure_group(auth_service, "sales")
        init_group_service(auth_service)
        
        token = auth_service.create_token(groups=["admin", "sales", "public"])
        
        result = is_admin(auth_tokens=[token], auth_service=auth_service)
        assert result is True

    def test_is_admin_no_token_returns_false(self, auth_service):
        """No token (anonymous) returns False."""
        init_group_service(auth_service)
        
        result = is_admin(auth_tokens=None, auth_service=auth_service)
        assert result is False

    def test_is_admin_invalid_token_returns_false(self, auth_service):
        """Invalid token returns False."""
        init_group_service(auth_service)
        
        result = is_admin(auth_tokens=["invalid-token"], auth_service=auth_service)
        assert result is False

    def test_is_admin_public_only_returns_false(self, auth_service):
        """Token with only public group returns False."""
        init_group_service(auth_service)
        
        # Public is reserved, should already exist
        public_token = auth_service.create_token(groups=["public"])
        
        result = is_admin(auth_tokens=[public_token], auth_service=auth_service)
        assert result is False


class TestRequireAdmin:
    """Test require_admin() function."""

    def test_require_admin_success_with_admin_group(self, auth_service):
        """require_admin() does not raise when admin group present."""
        init_group_service(auth_service)
        
        admin_token = auth_service.create_token(groups=["admin"])
        
        # Should not raise
        require_admin(auth_tokens=[admin_token], auth_service=auth_service)

    def test_require_admin_raises_without_admin_group(self, auth_service):
        """require_admin() raises AdminAccessDeniedError when admin group absent."""
        _ensure_group(auth_service, "regular-user")
        init_group_service(auth_service)
        
        user_token = auth_service.create_token(groups=["regular-user"])
        
        with pytest.raises(AdminAccessDeniedError) as exc_info:
            require_admin(auth_tokens=[user_token], auth_service=auth_service)
        
        # Check error message
        assert "Admin access required" in str(exc_info.value)
        assert "admin" in str(exc_info.value).lower()

    def test_require_admin_raises_for_anonymous(self, auth_service):
        """require_admin() raises for anonymous (no token)."""
        init_group_service(auth_service)
        
        with pytest.raises(AdminAccessDeniedError) as exc_info:
            require_admin(auth_tokens=None, auth_service=auth_service)
        
        assert "Admin access required" in str(exc_info.value)

    def test_require_admin_raises_for_invalid_token(self, auth_service):
        """require_admin() raises for invalid token."""
        init_group_service(auth_service)
        
        with pytest.raises(AdminAccessDeniedError) as exc_info:
            require_admin(auth_tokens=["invalid-garbage"], auth_service=auth_service)
        
        assert "Admin access required" in str(exc_info.value)

    def test_require_admin_success_with_multiple_groups(self, auth_service):
        """require_admin() succeeds when admin is one of multiple groups."""
        _ensure_group(auth_service, "sales")
        _ensure_group(auth_service, "marketing")
        init_group_service(auth_service)
        
        token = auth_service.create_token(groups=["sales", "admin", "marketing"])
        
        # Should not raise
        require_admin(auth_tokens=[token], auth_service=auth_service)

    def test_require_admin_error_message_provides_recovery(self, auth_service):
        """Error message provides recovery guidance."""
        init_group_service(auth_service)
        
        public_token = auth_service.create_token(groups=["public"])
        
        with pytest.raises(AdminAccessDeniedError) as exc_info:
            require_admin(auth_tokens=[public_token], auth_service=auth_service)
        
        error_msg = str(exc_info.value)
        # Should mention using a token with admin group
        assert "token" in error_msg.lower() or "admin" in error_msg.lower()

