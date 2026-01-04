"""Authentication tests for Source Tools.

Tests create_source behavior - requires authentication to create sources.
Any authenticated user can create sources in their own group.
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
    # Return a proper Source object with valid UUID format fields
    # Note: source_tools.py calls registry.create(), not registry.create_source()
    registry.create.return_value = Source(
        source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
        group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        name="Test Source",
        type=SourceType.NEWS_AGENCY,
        region="APAC",
        languages=["en"],
        trust_level=TrustLevel.MEDIUM,
    )
    # Add update return value
    registry.update.return_value = Source(
        source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
        group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        name="Updated Source",
        type=SourceType.NEWS_AGENCY,
        region="US",
        languages=["en", "es"],
        trust_level=TrustLevel.HIGH,
    )
    # Add soft_delete return value
    registry.soft_delete.return_value = Source(
        source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
        group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        name="Test Source",
        type=SourceType.NEWS_AGENCY,
        region="APAC",
        languages=["en"],
        trust_level=TrustLevel.MEDIUM,
        active=False,
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


@pytest.fixture
def update_source_fn(mock_source_registry):
    """Extract the update_source function from registered tools."""
    from mcp.server.fastmcp import FastMCP
    
    server = FastMCP("test-server")
    register_source_tools(server, mock_source_registry)
    
    for tool in server._tool_manager._tools.values():
        if tool.name == "update_source":
            return tool.fn
    
    raise RuntimeError("update_source tool not found")


@pytest.fixture
def delete_source_fn(mock_source_registry):
    """Extract the delete_source function from registered tools."""
    from mcp.server.fastmcp import FastMCP
    
    server = FastMCP("test-server")
    register_source_tools(server, mock_source_registry)
    
    for tool in server._tool_manager._tools.values():
        if tool.name == "delete_source":
            return tool.fn
    
    raise RuntimeError("delete_source tool not found")


class TestCreateSourceAlwaysRequiresAuth:
    """Tests that create_source behavior with authentication."""

    def test_create_source_no_auth_mode_writes_to_public(self, create_source_fn, mock_source_registry):
        """When auth is disabled, create_source writes to public group.
        
        POLICY DECISION: Rather than requiring auth even when disabled,
        anonymous writes go to the 'public' group. This allows systems
        to operate without auth while maintaining group-based access control.
        """
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
        
        # Assertion: Should succeed - anonymous writes go to public group
        success = result.get("success", result.get("status") == "success")
        assert success is True, f"create_source should succeed with public group when auth disabled, got: {result}"
        
        # Verify create was called (with public group)
        mock_source_registry.create.assert_called_once()

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
        
        # Verify create was NOT called
        mock_source_registry.create.assert_not_called()

    def test_create_source_non_admin_token_succeeds(self, vault_auth_service, create_source_fn, mock_source_registry):
        """create_source succeeds with any authenticated user token.
        
        Any authenticated user can create sources - the source is created
        in the group associated with their token.
        """
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
        
        # Assertion: Should succeed - any authenticated user can create sources
        success = result.get("success", result.get("status") == "success")
        assert success is True, f"Authenticated user should be able to create sources, got: {result}"
        
        # Verify create was called
        mock_source_registry.create.assert_called_once()

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
        
        # Verify create was called
        mock_source_registry.create.assert_called_once()


class TestUpdateSourceAuth:
    """Tests for update_source authentication and authorization."""

    def test_update_source_no_token_fails(self, vault_auth_service, update_source_fn, mock_source_registry):
        """update_source fails without authentication token."""
        init_group_service(auth_service=vault_auth_service)
        
        response = update_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Updated Name",
            auth_tokens=None,
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is False
        error_code = result.get("error_code") or result.get("error", {}).get("code")
        assert error_code == "AUTH_REQUIRED"
        mock_source_registry.update.assert_not_called()

    def test_update_source_with_valid_token_succeeds(self, vault_auth_service, update_source_fn, mock_source_registry):
        """update_source succeeds with valid authentication token."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = update_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Updated Name",
            trust_level="high",
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is True, f"Authenticated user should be able to update sources, got: {result}"
        mock_source_registry.update.assert_called_once()

    def test_update_source_partial_update(self, vault_auth_service, update_source_fn, mock_source_registry):
        """update_source only passes provided fields to registry."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = update_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            trust_level="high",  # Only updating trust_level
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is True
        
        # Verify call was made with only trust_level set
        call_kwargs = mock_source_registry.update.call_args.kwargs
        assert call_kwargs.get("name") is None
        assert call_kwargs.get("region") is None
        assert call_kwargs.get("languages") is None
        assert call_kwargs.get("trust_level") is not None

    def test_update_source_invalid_trust_level(self, vault_auth_service, update_source_fn, mock_source_registry):
        """update_source rejects invalid trust_level values."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = update_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            trust_level="invalid_level",
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is False
        error_code = result.get("error_code") or result.get("error", {}).get("code")
        assert error_code == "INVALID_TRUST_LEVEL"
        mock_source_registry.update.assert_not_called()

    def test_update_source_invalid_source_type(self, vault_auth_service, update_source_fn, mock_source_registry):
        """update_source rejects invalid source_type values."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = update_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            source_type="invalid_type",
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is False
        error_code = result.get("error_code") or result.get("error", {}).get("code")
        assert error_code == "INVALID_SOURCE_TYPE"
        mock_source_registry.update.assert_not_called()

    def test_update_source_returns_boost_factor(self, vault_auth_service, update_source_fn, mock_source_registry):
        """update_source response includes calculated boost_factor."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = update_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            trust_level="high",
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is True
        data = result.get("data", {})
        assert "boost_factor" in data
        assert data["boost_factor"] == 1.2  # high trust level = 1.2x boost


class TestDeleteSourceAuth:
    """Tests for delete_source authentication and soft-delete behavior."""

    def test_delete_source_no_token_fails(self, vault_auth_service, delete_source_fn, mock_source_registry):
        """delete_source fails without authentication token."""
        init_group_service(auth_service=vault_auth_service)
        
        response = delete_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            auth_tokens=None,
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is False
        error_code = result.get("error_code") or result.get("error", {}).get("code")
        assert error_code == "AUTH_REQUIRED"
        mock_source_registry.soft_delete.assert_not_called()

    def test_delete_source_with_valid_token_succeeds(self, vault_auth_service, delete_source_fn, mock_source_registry):
        """delete_source succeeds with valid authentication token."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = delete_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is True, f"Authenticated user should be able to delete sources, got: {result}"
        mock_source_registry.soft_delete.assert_called_once()

    def test_delete_source_returns_inactive_status(self, vault_auth_service, delete_source_fn, mock_source_registry):
        """delete_source returns source with active=False."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        response = delete_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            auth_tokens=[token],
        )
        
        result = parse_tool_response(response)
        
        success = result.get("success", result.get("status") == "success")
        assert success is True
        data = result.get("data", {})
        assert data.get("active") is False
        assert "deleted_at" in data

    def test_delete_source_calls_soft_delete(self, vault_auth_service, delete_source_fn, mock_source_registry):
        """delete_source calls soft_delete method, not hard delete."""
        init_group_service(auth_service=vault_auth_service)
        token = vault_auth_service.create_token(groups=["test-group"])
        
        delete_source_fn(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            auth_tokens=[token],
        )
        
        # Verify soft_delete was called with correct arguments
        mock_source_registry.soft_delete.assert_called_once()
        call_kwargs = mock_source_registry.soft_delete.call_args.kwargs
        assert call_kwargs.get("source_guid") == "7c9e6679-7425-40de-944b-e07fc1f90ae7"
        assert "access_groups" in call_kwargs


class TestSourceToolsRegistration:
    """Tests that all source tools are properly registered."""

    def test_all_source_tools_registered(self, mock_source_registry):
        """Verify all 5 source tools are registered."""
        from mcp.server.fastmcp import FastMCP
        
        server = FastMCP("test-server")
        register_source_tools(server, mock_source_registry)
        
        tool_names = [tool.name for tool in server._tool_manager._tools.values()]
        
        expected_tools = [
            "list_sources",
            "get_source",
            "create_source",
            "update_source",
            "delete_source",
        ]
        
        for tool_name in expected_tools:
            assert tool_name in tool_names, f"Tool '{tool_name}' not registered"
        
        assert len([t for t in tool_names if t in expected_tools]) == 5
