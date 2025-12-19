"""Authentication tests for Source Tools.

Tests create_source behavior - ALWAYS requires admin group authentication.
Even when auth is globally disabled, create_source requires admin credentials.
"""

import json
from unittest.mock import MagicMock

import pytest

from app.services.group_service import init_group_service
from app.tools.source_tools import register_source_tools

# Admin group constant
ADMIN_GROUP = "admin-group"


def parse_tool_response(response):
    """Parse MCP tool response to dict."""
    if hasattr(response, "__iter__"):
        for item in response:
            if hasattr(item, "text"):
                return json.loads(item.text)
    return {}


@pytest.fixture
def mock_source_registry():
    """Mock source registry for testing."""
    from app.models.source import Source, SourceType, TrustLevel
    
    registry = MagicMock()
    # Return a proper Source object
    registry.create_source.return_value = Source(
        source_guid="test-source-123",
        name="Test Source",
        type=SourceType.NEWS_AGENCY,
        region="APAC",
        languages=["en"],
        trust_level=TrustLevel.MEDIUM,
        group_name=ADMIN_GROUP,
    )
    return registry


@pytest.fixture
def create_source_fn(mock_source_registry):
    """Extract the create_source function from registered tools."""
    from mcp.server.fastmcp import FastMCP
    
    server = FastMCP("test-server")
    register_source_tools(server, mock_source_registry)
    
    # Get the decorated function directly
    for tool in server._tool_manager._tools.values():
        if tool.name == "create_source":
            return tool.fn
    
    raise RuntimeError("create_source tool not found")


class TestCreateSourceAlwaysRequiresAuth:
    """Tests that create_source ALWAYS requires admin authentication."""

    def test_create_source_no_auth_mode_still_requires_auth(self, create_source_fn, mock_source_registry):
        """create_source fails without token even when auth globally disabled."""
        # Setup: Initialize GroupService with auth disabled
        init_group_service(auth_service=None)
        
        # Action: Call create_source without auth_tokens
        response = create_source_fn(
            name="Test Source",
            source_type="news_agency",
            region="APAC",
            auth_tokens=None,  # No token provided
        )
        
        # Parse response
        result = parse_tool_response(response)
        
        # Assertion: Should fail - create_source ALWAYS requires auth
        success = result.get("success", result.get("status") == "success")
        assert success is False, f"create_source should require auth even in no-auth mode, got: {result}"
        error_code = result.get("error_code") or result.get("error", {}).get("code")
        assert error_code == "AUTH_REQUIRED", f"Expected AUTH_REQUIRED, got: {error_code}"
        
        # Verify create_source was NOT called
        mock_source_registry.create_source.assert_not_called()

    def test_create_source_auth_enabled_no_token(self, vault_auth_service, create_source_fn, mock_source_registry):
        """create_source fails without token when auth enabled."""
        # Setup: Initialize GroupService with auth enabled
        init_group_service(auth_service=vault_auth_service)
        
        # Action: Call create_source without token
        response = create_source_fn(
            name="Test Source",
            source_type="news_agency",
            region="APAC",
            auth_tokens=None,  # No token
        )
        
        # Parse response
        result = parse_tool_response(response)
        
        # Assertion: Should fail with AUTH_REQUIRED error
        success = result.get("success", result.get("status") == "success")
        assert success is False
        error_code = result.get("error_code") or result.get("error", {}).get("code")
        assert error_code == "AUTH_REQUIRED"
        
        # Verify create_source was NOT called
        mock_source_registry.create_source.assert_not_called()

    def test_create_source_non_admin_token_fails(self, vault_auth_service, create_source_fn, mock_source_registry):
        """create_source fails with non-admin token."""
        # Setup: Initialize GroupService with auth enabled
        init_group_service(auth_service=vault_auth_service)
        
        # Create token for a non-admin group
        token = vault_auth_service.create_token(groups=["regular-user-group"])
        
        # Action: Call create_source with non-admin token
        response = create_source_fn(
            name="Test Source",
            source_type="news_agency",
            region="APAC",
            auth_tokens=[token],
        )
        
        # Parse response
        result = parse_tool_response(response)
        
        # Assertion: Should fail - only admin can create sources
        success = result.get("success", result.get("status") == "success")
        assert success is False, f"Non-admin should not be able to create sources, got: {result}"
        
        # Verify create_source was NOT called
        mock_source_registry.create_source.assert_not_called()

    def test_create_source_admin_token_succeeds(self, vault_auth_service, create_source_fn, mock_source_registry):
        """create_source succeeds with admin token."""
        # Setup: Initialize GroupService with auth enabled
        init_group_service(auth_service=vault_auth_service)
        
        # Create token for admin group
        token = vault_auth_service.create_token(groups=[ADMIN_GROUP])
        
        # Action: Call create_source with admin token
        response = create_source_fn(
            name="Test Source",
            source_type="news_agency",
            region="APAC",
            auth_tokens=[token],
        )
        
        # Parse response
        result = parse_tool_response(response)
        
        # Assertion: Should succeed with admin token
        success = result.get("success", result.get("status") == "success")
        assert success is True, f"Admin should be able to create sources, got: {result}"
        
        # Verify create_source was called
        mock_source_registry.create_source.assert_called_once()
