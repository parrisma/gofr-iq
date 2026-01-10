"""Authentication tests for GroupService.

Tests resolve_write_group() behavior with auth enabled.

NOTE: Per TEST_AUTH_CONSOLIDATION_PLAN.md, all tests must run WITH AUTH ON.
No-auth mode tests have been removed/skipped.
"""

import pytest
from app.services.group_service import (
    init_group_service,
    resolve_write_group,
    get_group_service,
    PUBLIC_GROUP,
)


# =============================================================================
# SKIPPED: No-Auth Tests (violate "all tests WITH AUTH ON" requirement)
# =============================================================================
# These tests verify behavior when auth_service=None, which is no longer
# a supported configuration per TEST_AUTH_CONSOLIDATION_PLAN.md Step 7.
# If no-auth mode needs to be tested, create a separate test file that
# runs independently with explicit documentation.
# =============================================================================


@pytest.mark.skip(reason="No-auth mode tests skipped: all tests must run WITH AUTH ON (see TEST_AUTH_CONSOLIDATION_PLAN.md)")
class TestResolveWriteGroupNoAuth:
    """Tests for resolve_write_group when auth is disabled.
    
    SKIPPED: These tests violate the requirement that all tests run WITH AUTH ON.
    """

    def test_resolve_write_group_no_auth_no_token(self):
        """When auth is disabled globally, anonymous users should write to 'public'."""
        # Setup: GroupService with auth_service=None (auth disabled)
        init_group_service(auth_service=None)
        
        # Verify setup
        service = get_group_service()
        assert service.auth_service is None, "Auth service should be None"
        
        # Action: Call resolve_write_group without tokens
        result = resolve_write_group(auth_tokens=None)
        
        # Expected: Should return "public" not None
        assert result == PUBLIC_GROUP, f"Expected '{PUBLIC_GROUP}', got {result}"

    def test_resolve_write_group_no_auth_empty_list(self):
        """Empty auth_tokens list with no auth should return 'public'."""
        # Setup: GroupService with auth_service=None
        init_group_service(auth_service=None)
        
        # Action: Call with empty list
        result = resolve_write_group(auth_tokens=[])
        
        # Expected: Should return "public"
        assert result == PUBLIC_GROUP, f"Expected '{PUBLIC_GROUP}', got {result}"


class TestResolveWriteGroupAuthEnabled:
    """Tests for resolve_write_group when auth is enabled."""

    def test_resolve_write_group_auth_enabled_no_token(self, vault_auth_service):
        """When auth is enabled, anonymous users cannot write."""
        # Setup: GroupService with real AuthService
        auth_service = vault_auth_service
        init_group_service(auth_service=auth_service)
        
        # Verify setup
        service = get_group_service()
        assert service.auth_service is not None, "Auth service should be set"
        
        # Action: Call resolve_write_group without tokens
        result = resolve_write_group(auth_tokens=None)
        
        # Expected: Should return None (no write access)
        assert result is None, f"Expected None, got {result}"

    def test_resolve_write_group_auth_enabled_empty_list(self, vault_auth_service):
        """Empty auth_tokens list with auth enabled should return None."""
        # Setup: GroupService with real AuthService
        auth_service = vault_auth_service
        init_group_service(auth_service=auth_service)
        
        # Action: Call with empty list
        result = resolve_write_group(auth_tokens=[])
        
        # Expected: Should return None
        assert result is None, f"Expected None, got {result}"

    def test_resolve_write_group_auth_enabled_with_valid_token(self, vault_auth_service):
        """When auth is enabled, valid token should return group."""
        # Setup: GroupService with real AuthService
        auth_service = vault_auth_service
        init_group_service(auth_service=auth_service)
        
        # Create valid token for a specific group (must be pre-created in conftest.py)
        token = auth_service.create_token(groups=["premium-group"])
        
        # Action: Call with token
        result = resolve_write_group(auth_tokens=[token])
        
        # Expected: Should return the token's primary group
        assert result == "premium-group", f"Expected 'premium-group', got {result}"
