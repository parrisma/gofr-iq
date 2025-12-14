"""Tests for Client Tools

Unit tests for the MCP client tools for client management and personalized feeds.

NOTE: These tools are NOT exposed by the default MCP server configuration.
They remain available for direct use but are not registered via register_all_tools.

Group Access Control:
    These tests mock the auth context to simulate authenticated requests.
    Tools no longer accept group_guid/group_guids as parameters - they extract
    the group from the JWT token in the request context.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from app.services.graph_index import GraphIndex, GraphNode, NodeLabel, RelationType
from app.tools.client_tools import register_client_tools


# ============================================================================
# Test Group Constants
# ============================================================================

TEST_GROUP = "test-group-123"
TEST_PUBLIC_GROUP = "public"


# ============================================================================
# Auth Context Helper
# ============================================================================


def with_auth_context(group: str = TEST_GROUP):
    """Decorator to mock auth context for a test function."""
    def decorator(fn):
        @patch('app.services.group_service.get_write_group_from_context')
        @patch('app.services.group_service.get_permitted_groups_from_context')
        def wrapper(mock_permitted, mock_write, *args, **kwargs):
            mock_write.return_value = group
            mock_permitted.return_value = [TEST_PUBLIC_GROUP, group]
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_graph_index() -> MagicMock:
    """Create a mock GraphIndex"""
    mock = MagicMock(spec=GraphIndex)
    mock.RelationType = RelationType
    mock._get_session = MagicMock()
    return mock


@pytest.fixture
def mcp_server() -> FastMCP:
    """Create a FastMCP server for testing"""
    return FastMCP("test-client-tools")


@pytest.fixture
def registered_tools(mcp_server: FastMCP, mock_graph_index: MagicMock) -> dict[str, Any]:
    """Register client tools and return them"""
    register_client_tools(mcp_server, mock_graph_index)
    return {tool.name: tool for tool in mcp_server._tool_manager._tools.values()}


def parse_response(response: Any) -> dict[str, Any]:
    """Parse MCP tool response to dict"""
    if hasattr(response, "__iter__"):
        for item in response:
            if hasattr(item, "text"):
                return json.loads(item.text)
    return {}


def get_tool_fn(mcp_server: FastMCP, tool_name: str) -> Any:
    """Get a tool function by name, raising if not found"""
    for tool in mcp_server._tool_manager._tools.values():
        if tool.name == tool_name:
            return tool.fn
    raise ValueError(f"Tool '{tool_name}' not found")


# ============================================================================
# Tool Registration Tests
# ============================================================================


class TestToolRegistration:
    """Tests for tool registration"""

    def test_tools_registered(self, registered_tools: dict[str, Any]) -> None:
        """Test that all client tools are registered"""
        assert "create_client" in registered_tools
        assert "get_client_feed" in registered_tools
        assert "add_to_portfolio" in registered_tools
        assert "add_to_watchlist" in registered_tools

    def test_create_client_description(self, registered_tools: dict[str, Any]) -> None:
        """Test create_client has proper description"""
        tool = registered_tools["create_client"]
        assert "client profile" in tool.description.lower()
        assert "personalized" in tool.description.lower()

    def test_get_client_feed_description(self, registered_tools: dict[str, Any]) -> None:
        """Test get_client_feed has proper description"""
        tool = registered_tools["get_client_feed"]
        assert "personalized" in tool.description.lower()
        assert "news feed" in tool.description.lower()


# ============================================================================
# Create Client Tests
# ============================================================================


class TestCreateClient:
    """Tests for create_client tool"""

    @patch('app.tools.client_tools.get_write_group_from_context')
    def test_create_client_success(
        self,
        mock_write_group: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test successful client creation"""
        mock_write_group.return_value = TEST_GROUP
        register_client_tools(mcp_server, mock_graph_index)
        
        # Mock return values
        mock_graph_index.create_client.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="test-client-guid",
            properties={"name": "Test Fund"},
        )
        mock_graph_index.create_client_profile.return_value = GraphNode(
            label=NodeLabel.CLIENT_PROFILE,
            guid="test-profile-guid",
            properties={},
        )
        mock_graph_index.create_portfolio.return_value = GraphNode(
            label=NodeLabel.PORTFOLIO,
            guid="test-portfolio-guid",
            properties={},
        )
        mock_graph_index.create_watchlist.return_value = GraphNode(
            label=NodeLabel.WATCHLIST,
            guid="test-watchlist-guid",
            properties={},
        )
        
        # Get the tool function
        tool_fn = get_tool_fn(mcp_server, "create_client")
        
        # Call the tool - no group_guid parameter needed
        response = tool_fn(
            name="Test Fund",
            client_type="HEDGE_FUND",
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert "client_guid" in result["data"]
        assert result["data"]["name"] == "Test Fund"
        assert result["data"]["client_type"] == "HEDGE_FUND"
        assert result["data"]["group_guid"] == TEST_GROUP

    @patch('app.tools.client_tools.get_write_group_from_context')
    def test_create_client_with_profile(
        self,
        mock_write_group: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test client creation with profile options"""
        mock_write_group.return_value = TEST_GROUP
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_graph_index.create_client.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="test-guid",
            properties={},
        )
        mock_graph_index.create_client_profile.return_value = GraphNode(
            label=NodeLabel.CLIENT_PROFILE,
            guid="profile-guid",
            properties={},
        )
        mock_graph_index.create_portfolio.return_value = GraphNode(
            label=NodeLabel.PORTFOLIO,
            guid="portfolio-guid",
            properties={},
        )
        mock_graph_index.create_watchlist.return_value = GraphNode(
            label=NodeLabel.WATCHLIST,
            guid="watchlist-guid",
            properties={},
        )
        
        tool_fn = get_tool_fn(mcp_server, "create_client")
        
        # Call without group_guid - extracted from context
        response = tool_fn(
            name="Long Only Fund",
            client_type="LONG_ONLY",
            mandate_type="equity_long_only",
            benchmark="SPY",
            horizon="long",
            esg_constrained=True,
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["profile"]["mandate_type"] == "equity_long_only"
        assert result["data"]["profile"]["benchmark"] == "SPY"
        assert result["data"]["profile"]["esg_constrained"] is True


# ============================================================================
# Get Client Feed Tests
# ============================================================================


class TestGetClientFeed:
    """Tests for get_client_feed tool"""

    @patch('app.tools.client_tools.get_permitted_groups_from_context')
    def test_get_feed_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test successful feed retrieval"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        # Mock client exists
        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={"name": "Test Fund"},
        )
        
        # Mock feed results
        mock_graph_index.get_client_feed.return_value = [
            {
                "document_guid": "doc-1",
                "title": "Apple Beats Earnings",
                "impact_score": 75,
                "impact_tier": "GOLD",
                "current_relevance": 85.0,
                "affected_instruments": ["AAPL"],
                "created_at": "2025-01-15T10:00:00Z",
            },
            {
                "document_guid": "doc-2",
                "title": "Fed Holds Rates",
                "impact_score": 80,
                "impact_tier": "PLATINUM",
                "current_relevance": 80.0,
                "affected_instruments": ["SPY", "QQQ"],
                "created_at": "2025-01-15T09:00:00Z",
            },
        ]
        
        tool_fn = get_tool_fn(mcp_server, "get_client_feed")
        
        # Call without group_guids - extracted from context
        response = tool_fn(
            client_guid="client-123",
            limit=10,
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["total_count"] == 2
        assert len(result["data"]["articles"]) == 2
        assert result["data"]["articles"][0]["title"] == "Apple Beats Earnings"

    @patch('app.tools.client_tools.get_permitted_groups_from_context')
    def test_get_feed_with_filters(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test feed with impact filters"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={},
        )
        mock_graph_index.get_client_feed.return_value = []
        
        tool_fn = get_tool_fn(mcp_server, "get_client_feed")
        
        # Call without group_guids
        response = tool_fn(
            client_guid="client-123",
            min_impact_score=70,
            impact_tiers=["PLATINUM", "GOLD"],
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["filters_applied"]["min_impact_score"] == 70
        assert result["data"]["filters_applied"]["impact_tiers"] == ["PLATINUM", "GOLD"]

    @patch('app.tools.client_tools.get_permitted_groups_from_context')
    def test_get_feed_client_not_found(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test feed when client doesn't exist"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_graph_index.get_node.return_value = None
        
        tool_fn = get_tool_fn(mcp_server, "get_client_feed")
        
        # Call without group_guids
        response = tool_fn(
            client_guid="nonexistent",
        )
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "CLIENT_NOT_FOUND"


# ============================================================================
# Add to Portfolio Tests
# ============================================================================


class TestAddToPortfolio:
    """Tests for add_to_portfolio tool"""

    def test_add_holding_success(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test adding a holding to portfolio"""
        register_client_tools(mcp_server, mock_graph_index)
        
        # Mock session for portfolio lookup
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"portfolio_guid": "portfolio-123"}
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "add_to_portfolio")
        
        response = tool_fn(
            client_guid="client-123",
            ticker="AAPL",
            weight=0.15,
            shares=1000,
            avg_cost=150.0,
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["ticker"] == "AAPL"
        assert result["data"]["weight"] == 0.15
        
        # Verify add_holding was called
        mock_graph_index.add_holding.assert_called_once()

    def test_add_holding_portfolio_not_found(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test adding when portfolio doesn't exist"""
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = None  # No portfolio
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "add_to_portfolio")
        
        response = tool_fn(
            client_guid="client-123",
            ticker="AAPL",
            weight=0.10,
        )
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "PORTFOLIO_NOT_FOUND"


# ============================================================================
# Add to Watchlist Tests
# ============================================================================


class TestAddToWatchlist:
    """Tests for add_to_watchlist tool"""

    def test_add_to_watchlist_success(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test adding to watchlist"""
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"watchlist_guid": "watchlist-123"}
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "add_to_watchlist")
        
        response = tool_fn(
            client_guid="client-123",
            ticker="TSLA",
            alert_threshold=60.0,
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["ticker"] == "TSLA"
        assert result["data"]["alert_threshold"] == 60.0
        
        # Verify relationship was created
        mock_graph_index.create_relationship.assert_called()

    def test_add_to_watchlist_not_found(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test adding when watchlist doesn't exist"""
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "add_to_watchlist")
        
        response = tool_fn(
            client_guid="client-123",
            ticker="TSLA",
        )
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "WATCHLIST_NOT_FOUND"
