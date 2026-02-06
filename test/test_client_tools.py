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
from app.services.query_service import QueryService
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
        @patch('app.tools.client_tools.resolve_write_group')
        @patch('app.tools.client_tools.resolve_permitted_groups')
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
def mock_query_service() -> MagicMock:
    """Create a mock QueryService"""
    return MagicMock(spec=QueryService)


@pytest.fixture
def mcp_server() -> FastMCP:
    """Create a FastMCP server for testing"""
    return FastMCP("test-client-tools")


@pytest.fixture
def registered_tools(
    mcp_server: FastMCP,
    mock_graph_index: MagicMock,
    mock_query_service: MagicMock,
) -> dict[str, Any]:
    """Register client tools and return them"""
    register_client_tools(mcp_server, mock_graph_index, query_service=mock_query_service)
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
        assert "get_top_client_news" in registered_tools
        assert "add_to_portfolio" in registered_tools
        assert "add_to_watchlist" in registered_tools
        # New tools
        assert "list_clients" in registered_tools
        assert "get_client_profile" in registered_tools
        assert "get_portfolio_holdings" in registered_tools
        assert "get_watchlist_items" in registered_tools
        assert "update_client_profile" in registered_tools
        assert "remove_from_portfolio" in registered_tools
        assert "remove_from_watchlist" in registered_tools
        assert "defunct_client" in registered_tools
        assert "restore_client" in registered_tools
        assert "delete_client" in registered_tools
        assert "repair_client" in registered_tools
        assert "move_client_group" in registered_tools
        assert "set_client_type" in registered_tools

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

    @patch('app.tools.client_tools.get_group_uuid_by_name')
    @patch('app.tools.client_tools.resolve_write_group')
    def test_create_client_success(
        self,
        mock_write_group: MagicMock,
        mock_get_group_uuid: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test successful client creation"""
        mock_write_group.return_value = TEST_GROUP
        mock_get_group_uuid.return_value = TEST_GROUP  # Return UUID for the group
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

    @patch('app.tools.client_tools.get_group_uuid_by_name')
    @patch('app.tools.client_tools.resolve_write_group')
    def test_create_client_with_profile(
        self,
        mock_write_group: MagicMock,
        mock_get_group_uuid: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test client creation with profile options"""
        mock_write_group.return_value = TEST_GROUP
        mock_get_group_uuid.return_value = TEST_GROUP  # Return UUID for the group
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

    @patch('app.tools.client_tools.resolve_permitted_groups')
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

    @patch('app.tools.client_tools.resolve_permitted_groups')
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

    @patch('app.tools.client_tools.resolve_permitted_groups')
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

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_feed_defunct_client(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test feed blocked for defunct client"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={"status": "defunct"},
        )

        tool_fn = get_tool_fn(mcp_server, "get_client_feed")

        response = tool_fn(
            client_guid="client-123",
        )

        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "CLIENT_DEFUNCT"


# ============================================================================
# Get Top Client News Tests
# ============================================================================


class TestGetTopClientNews:
    """Tests for get_top_client_news tool"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_top_news_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
        mock_query_service: MagicMock,
    ) -> None:
        """Test successful top news retrieval"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(
            mcp_server,
            mock_graph_index,
            query_service=mock_query_service,
        )

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={"name": "Test Fund"},
        )

        mock_query_service.get_top_client_news.return_value = [
            {
                "document_guid": "doc-1",
                "title": "Client-Relevant News",
                "impact_score": 85,
                "impact_tier": "GOLD",
                "relevance_score": 0.92,
                "affected_instruments": ["AAPL"],
                "created_at": "2025-01-15T10:00:00Z",
                "reasons": ["DIRECT_HOLDING"],
                "why_it_matters": "Direct holding impacted by earnings beat.",
            }
        ]

        tool_fn = get_tool_fn(mcp_server, "get_top_client_news")

        response = tool_fn(
            client_guid="client-123",
            limit=3,
        )

        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["total_count"] == 1
        assert result["data"]["articles"][0]["title"] == "Client-Relevant News"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_top_news_without_query_service(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test error when QueryService is not configured"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={"name": "Test Fund"},
        )

        tool_fn = get_tool_fn(mcp_server, "get_top_client_news")

        response = tool_fn(
            client_guid="client-123",
            limit=3,
        )

        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "QUERY_SERVICE_UNAVAILABLE"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_top_news_client_not_found(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
        mock_query_service: MagicMock,
    ) -> None:
        """Test error when client is not found"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(
            mcp_server,
            mock_graph_index,
            query_service=mock_query_service,
        )

        mock_graph_index.get_node.return_value = None

        tool_fn = get_tool_fn(mcp_server, "get_top_client_news")

        response = tool_fn(
            client_guid="nonexistent-client-guid-1234",
            limit=3,
        )

        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "CLIENT_NOT_FOUND"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_top_news_defunct_client(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
        mock_query_service: MagicMock,
    ) -> None:
        """Test error when client is defunct"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(
            mcp_server,
            mock_graph_index,
            query_service=mock_query_service,
        )

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={
                "name": "Defunct Fund",
                "status": "defunct",
                "defunct_at": "2025-01-01T00:00:00Z",
                "defunct_reason": "Client closed",
            },
        )

        tool_fn = get_tool_fn(mcp_server, "get_top_client_news")

        response = tool_fn(
            client_guid="client-123",
            limit=3,
        )

        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "CLIENT_DEFUNCT"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_top_news_with_impact_filters(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
        mock_query_service: MagicMock,
    ) -> None:
        """Test top news with impact score and tier filters"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(
            mcp_server,
            mock_graph_index,
            query_service=mock_query_service,
        )

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={"name": "Test Fund"},
        )

        mock_query_service.get_top_client_news.return_value = [
            {
                "document_guid": "doc-platinum",
                "title": "High Impact News",
                "impact_score": 95,
                "impact_tier": "PLATINUM",
                "relevance_score": 0.95,
                "affected_instruments": ["AAPL"],
                "created_at": "2025-01-15T10:00:00Z",
                "reasons": ["DIRECT_HOLDING"],
                "why_it_matters": "Critical update.",
            }
        ]

        tool_fn = get_tool_fn(mcp_server, "get_top_client_news")

        response = tool_fn(
            client_guid="client-123",
            limit=5,
            min_impact_score=80.0,
            impact_tiers=["PLATINUM", "GOLD"],
        )

        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["filters_applied"]["min_impact_score"] == 80.0
        assert result["data"]["filters_applied"]["impact_tiers"] == ["PLATINUM", "GOLD"]

        mock_query_service.get_top_client_news.assert_called_once()
        call_kwargs = mock_query_service.get_top_client_news.call_args[1]
        assert call_kwargs["min_impact_score"] == 80.0
        assert call_kwargs["impact_tiers"] == ["PLATINUM", "GOLD"]

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_top_news_with_time_window(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
        mock_query_service: MagicMock,
    ) -> None:
        """Test top news with custom time window"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(
            mcp_server,
            mock_graph_index,
            query_service=mock_query_service,
        )

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={"name": "Test Fund"},
        )

        mock_query_service.get_top_client_news.return_value = []

        tool_fn = get_tool_fn(mcp_server, "get_top_client_news")

        response = tool_fn(
            client_guid="client-123",
            limit=3,
            time_window_hours=48,
        )

        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["filters_applied"]["time_window_hours"] == 48

        call_kwargs = mock_query_service.get_top_client_news.call_args[1]
        assert call_kwargs["time_window_hours"] == 48

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_top_news_disable_lateral_graph(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
        mock_query_service: MagicMock,
    ) -> None:
        """Test top news without lateral graph expansion"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(
            mcp_server,
            mock_graph_index,
            query_service=mock_query_service,
        )

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={"name": "Test Fund"},
        )

        mock_query_service.get_top_client_news.return_value = []

        tool_fn = get_tool_fn(mcp_server, "get_top_client_news")

        response = tool_fn(
            client_guid="client-123",
            limit=3,
            include_portfolio=True,
            include_watchlist=False,
            include_lateral_graph=False,
        )

        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["filters_applied"]["include_portfolio"] is True
        assert result["data"]["filters_applied"]["include_watchlist"] is False
        assert result["data"]["filters_applied"]["include_lateral_graph"] is False

        call_kwargs = mock_query_service.get_top_client_news.call_args[1]
        assert call_kwargs["include_portfolio"] is True
        assert call_kwargs["include_watchlist"] is False
        assert call_kwargs["include_lateral_graph"] is False

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_top_news_multiple_reasons(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
        mock_query_service: MagicMock,
    ) -> None:
        """Test top news with multiple relevance reasons"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(
            mcp_server,
            mock_graph_index,
            query_service=mock_query_service,
        )

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.CLIENT,
            guid="client-123",
            properties={"name": "Test Fund"},
        )

        mock_query_service.get_top_client_news.return_value = [
            {
                "document_guid": "doc-1",
                "title": "Apple Supply Chain Disruption",
                "impact_score": 88,
                "impact_tier": "GOLD",
                "relevance_score": 0.95,
                "affected_instruments": ["AAPL", "TSM"],
                "created_at": "2025-01-15T10:00:00Z",
                "reasons": ["DIRECT_HOLDING", "SUPPLY_CHAIN", "SEMANTIC_MATCH"],
                "why_it_matters": "Direct holding AAPL and supply chain TSM both affected.",
            },
            {
                "document_guid": "doc-2",
                "title": "Tech Sector Earnings Preview",
                "impact_score": 72,
                "impact_tier": "SILVER",
                "relevance_score": 0.82,
                "affected_instruments": ["GOOGL", "MSFT"],
                "created_at": "2025-01-15T09:00:00Z",
                "reasons": ["WATCHLIST", "PEER"],
                "why_it_matters": "Watchlist items in same sector.",
            },
        ]

        tool_fn = get_tool_fn(mcp_server, "get_top_client_news")

        response = tool_fn(
            client_guid="client-123",
            limit=5,
        )

        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["total_count"] == 2

        first_article = result["data"]["articles"][0]
        assert "DIRECT_HOLDING" in first_article["reasons"]
        assert "SUPPLY_CHAIN" in first_article["reasons"]
        assert "SEMANTIC_MATCH" in first_article["reasons"]

        second_article = result["data"]["articles"][1]
        assert "WATCHLIST" in second_article["reasons"]
        assert "PEER" in second_article["reasons"]


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


# ============================================================================
# List Clients Tests
# ============================================================================


class TestListClients:
    """Tests for list_clients tool"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_list_clients_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test listing clients successfully"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        # Mock session for client query
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            {
                "client_guid": "client-1",
                "name": "Citadel",
                "client_type": "HEDGE_FUND",
                "group_guid": TEST_GROUP,
                "created_at": "2025-01-01T00:00:00Z",
                "status": "active",
            },
            {
                "client_guid": "client-2",
                "name": "BlackRock",
                "client_type": "LONG_ONLY",
                "group_guid": TEST_GROUP,
                "created_at": "2025-01-02T00:00:00Z",
                "status": "active",
            },
        ])
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "list_clients")
        
        response = tool_fn()
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["total_count"] == 2
        assert len(result["data"]["clients"]) == 2
        assert result["data"]["clients"][0]["name"] == "Citadel"
        assert result["data"]["clients"][1]["name"] == "BlackRock"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_list_clients_with_type_filter(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test listing clients filtered by type"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([
            {
                "client_guid": "client-1",
                "name": "Citadel",
                "client_type": "HEDGE_FUND",
                "group_guid": TEST_GROUP,
                "created_at": "2025-01-01T00:00:00Z",
                "status": "active",
            },
        ])
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "list_clients")
        
        response = tool_fn(client_type="HEDGE_FUND")
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["filters_applied"]["client_type"] == "HEDGE_FUND"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_list_clients_empty(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test listing when no clients exist"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "list_clients")
        
        response = tool_fn()
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["total_count"] == 0
        assert result["data"]["clients"] == []


# ============================================================================
# Get Client Profile Tests
# ============================================================================


class TestGetClientProfile:
    """Tests for get_client_profile tool"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_profile_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting client profile successfully"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "client_guid": "client-123",
            "name": "Citadel",
            "alert_frequency": "realtime",
            "impact_threshold": 50.0,
            "created_at": "2025-01-01T00:00:00Z",
            "client_type": "HEDGE_FUND",
            "group_guid": TEST_GROUP,
            "status": "active",
            "defunct_at": None,
            "defunct_reason": None,
            "profile_guid": "profile-123",
            "mandate_type": "equity_long_short",
            "mandate_text": None,
            "horizon": "short",
            "esg_constrained": False,
            "restrictions_json": None,
            "benchmark": "SPY",
            "portfolio_guid": "portfolio-123",
            "watchlist_guid": "watchlist-123",
        }
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "get_client_profile")
        
        response = tool_fn(client_guid="client-123")
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["name"] == "Citadel"
        assert result["data"]["client_type"] == "HEDGE_FUND"
        assert result["data"]["profile"]["mandate_type"] == "equity_long_short"
        assert result["data"]["settings"]["alert_frequency"] == "realtime"
        assert result["data"]["portfolio_guid"] == "portfolio-123"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_profile_not_found(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting profile for non-existent client"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "get_client_profile")
        
        response = tool_fn(client_guid="nonexistent-guid-1234-5678-901234567890")
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "CLIENT_NOT_FOUND"

    @patch('app.tools.client_tools.get_group_uuids_by_names')
    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_profile_access_denied(
        self,
        mock_permitted_groups: MagicMock,
        mock_get_group_uuids: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test access denied for client in different group"""
        mock_permitted_groups.return_value = ["other-group"]
        # Return a UUID for "other-group" that differs from TEST_GROUP
        mock_get_group_uuids.return_value = ["other-group-uuid"]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "client_guid": "client-123",
            "name": "Citadel",
            "group_guid": TEST_GROUP,  # Different from permitted
            "alert_frequency": "realtime",
            "impact_threshold": 50.0,
            "created_at": None,
            "client_type": "HEDGE_FUND",
            "status": None,
            "defunct_at": None,
            "defunct_reason": None,
            "profile_guid": None,
            "mandate_type": None,
            "horizon": None,
            "esg_constrained": None,
            "benchmark": None,
            "portfolio_guid": None,
            "watchlist_guid": None,
        }
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "get_client_profile")
        
        response = tool_fn(client_guid="client-123")
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "ACCESS_DENIED"


# ============================================================================
# Get Portfolio Holdings Tests
# ============================================================================


class TestGetPortfolioHoldings:
    """Tests for get_portfolio_holdings tool"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_holdings_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting portfolio holdings successfully"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        
        # First call: access check
        access_result = MagicMock()
        access_result.single.return_value = {
            "group_guid": TEST_GROUP,
            "client_name": "Citadel",
        }
        
        # Second call: holdings query
        holdings_result = MagicMock()
        holdings_result.__iter__ = lambda self: iter([
            {
                "portfolio_guid": "portfolio-123",
                "ticker": "AAPL",
                "instrument_name": "Apple Inc",
                "weight": 0.25,
                "shares": 10000,
                "avg_cost": 150.0,
                "added_at": "2025-01-01T00:00:00Z",
            },
            {
                "portfolio_guid": "portfolio-123",
                "ticker": "MSFT",
                "instrument_name": "Microsoft Corp",
                "weight": 0.15,
                "shares": 5000,
                "avg_cost": 380.0,
                "added_at": "2025-01-02T00:00:00Z",
            },
        ])
        
        mock_session.run.side_effect = [access_result, holdings_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "get_portfolio_holdings")
        
        response = tool_fn(client_guid="client-123")
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["holding_count"] == 2
        assert result["data"]["total_weight"] == 0.4
        assert result["data"]["holdings"][0]["ticker"] == "AAPL"
        assert result["data"]["holdings"][0]["weight_pct"] == "25.0%"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_holdings_empty_portfolio(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting empty portfolio"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        
        access_result = MagicMock()
        access_result.single.return_value = {
            "group_guid": TEST_GROUP,
            "client_name": "Citadel",
        }
        
        holdings_result = MagicMock()
        holdings_result.__iter__ = lambda self: iter([
            {
                "portfolio_guid": "portfolio-123",
                "ticker": None,  # No holdings
                "instrument_name": None,
                "weight": None,
                "shares": None,
                "avg_cost": None,
                "added_at": None,
            },
        ])
        
        mock_session.run.side_effect = [access_result, holdings_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "get_portfolio_holdings")
        
        response = tool_fn(client_guid="client-123")
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["holding_count"] == 0
        assert result["data"]["holdings"] == []


# ============================================================================
# Get Watchlist Items Tests
# ============================================================================


class TestGetWatchlistItems:
    """Tests for get_watchlist_items tool"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_get_watchlist_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting watchlist items successfully"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        
        access_result = MagicMock()
        access_result.single.return_value = {
            "group_guid": TEST_GROUP,
            "client_name": "Citadel",
        }
        
        watchlist_result = MagicMock()
        watchlist_result.__iter__ = lambda self: iter([
            {
                "watchlist_guid": "watchlist-123",
                "watchlist_name": "Citadel Watchlist",
                "ticker": "TSLA",
                "instrument_name": "Tesla Inc",
                "alert_threshold": 60.0,
                "added_at": "2025-01-01T00:00:00Z",
            },
            {
                "watchlist_guid": "watchlist-123",
                "watchlist_name": "Citadel Watchlist",
                "ticker": "NVDA",
                "instrument_name": "NVIDIA Corp",
                "alert_threshold": 70.0,
                "added_at": "2025-01-02T00:00:00Z",
            },
        ])
        
        mock_session.run.side_effect = [access_result, watchlist_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "get_watchlist_items")
        
        response = tool_fn(client_guid="client-123")
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["item_count"] == 2
        assert result["data"]["items"][0]["ticker"] == "TSLA"
        assert result["data"]["items"][0]["alert_threshold"] == 60.0


# ============================================================================
# Update Client Profile Tests
# ============================================================================


class TestUpdateClientProfile:
    """Tests for update_client_profile tool"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_update_profile_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test updating client profile successfully"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        
        # Access check result
        access_result = MagicMock()
        access_result.single.return_value = {
            "group_guid": TEST_GROUP,
            "client_name": "Citadel",
            "profile_guid": "profile-123",
        }
        
        # Update results (no return needed)
        update_result = MagicMock()
        
        # Final fetch result
        fetch_result = MagicMock()
        fetch_result.single.return_value = {
            "client_guid": "client-123",
            "name": "Citadel",
            "alert_frequency": "daily",
            "impact_threshold": 70.0,
            "client_type": "HEDGE_FUND",
            "group_guid": TEST_GROUP,
            "mandate_type": "equity_long_short",
            "mandate_text": None,
            "horizon": "short",
            "esg_constrained": False,
            "benchmark": "SPY",
        }
        
        mock_session.run.side_effect = [access_result, update_result, fetch_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "update_client_profile")
        
        response = tool_fn(
            client_guid="client-123",
            alert_frequency="daily",
            impact_threshold=70.0,
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert "alert_frequency" in result["data"]["changes"]
        assert "impact_threshold" in result["data"]["changes"]
        assert result["data"]["settings"]["alert_frequency"] == "daily"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_update_profile_no_changes(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test update with no fields provided"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        tool_fn = get_tool_fn(mcp_server, "update_client_profile")
        
        response = tool_fn(client_guid="client-123")
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "NO_UPDATES_PROVIDED"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_update_profile_invalid_frequency(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test update with invalid alert frequency"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        tool_fn = get_tool_fn(mcp_server, "update_client_profile")
        
        response = tool_fn(
            client_guid="client-123",
            alert_frequency="invalid",
        )
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_ALERT_FREQUENCY"


# ============================================================================
# Remove from Portfolio Tests
# ============================================================================


class TestRemoveFromPortfolio:
    """Tests for remove_from_portfolio tool"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_remove_holding_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test removing holding successfully"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        
        access_result = MagicMock()
        access_result.single.return_value = {
            "group_guid": TEST_GROUP,
            "client_name": "Citadel",
        }
        
        delete_result = MagicMock()
        delete_result.single.return_value = {"deleted": 1}
        
        count_result = MagicMock()
        count_result.single.return_value = {"remaining": 5}
        
        mock_session.run.side_effect = [access_result, delete_result, count_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "remove_from_portfolio")
        
        response = tool_fn(
            client_guid="client-123",
            ticker="AAPL",
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["ticker_removed"] == "AAPL"
        assert result["data"]["remaining_holdings"] == 5

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_remove_holding_not_found(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test removing holding that doesn't exist"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        
        access_result = MagicMock()
        access_result.single.return_value = {
            "group_guid": TEST_GROUP,
            "client_name": "Citadel",
        }
        
        delete_result = MagicMock()
        delete_result.single.return_value = {"deleted": 0}  # Nothing deleted
        
        mock_session.run.side_effect = [access_result, delete_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "remove_from_portfolio")
        
        response = tool_fn(
            client_guid="client-123",
            ticker="XYZ",
        )
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "HOLDING_NOT_FOUND"


# ============================================================================
# Remove from Watchlist Tests
# ============================================================================


class TestRemoveFromWatchlist:
    """Tests for remove_from_watchlist tool"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_remove_watch_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test removing from watchlist successfully"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        
        access_result = MagicMock()
        access_result.single.return_value = {
            "group_guid": TEST_GROUP,
            "client_name": "Citadel",
        }
        
        delete_result = MagicMock()
        delete_result.single.return_value = {"deleted": 1}
        
        count_result = MagicMock()
        count_result.single.return_value = {"remaining": 3}
        
        mock_session.run.side_effect = [access_result, delete_result, count_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "remove_from_watchlist")
        
        response = tool_fn(
            client_guid="client-123",
            ticker="TSLA",
        )
        
        result = parse_response(response)
        
        assert result["status"] == "success"
        assert result["data"]["ticker_removed"] == "TSLA"
        assert result["data"]["remaining_watched"] == 3

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_remove_watch_not_found(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test removing watch that doesn't exist"""
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)
        
        mock_session = MagicMock()
        
        access_result = MagicMock()
        access_result.single.return_value = {
            "group_guid": TEST_GROUP,
            "client_name": "Citadel",
        }
        
        delete_result = MagicMock()
        delete_result.single.return_value = {"deleted": 0}
        
        mock_session.run.side_effect = [access_result, delete_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session
        
        tool_fn = get_tool_fn(mcp_server, "remove_from_watchlist")
        
        response = tool_fn(
            client_guid="client-123",
            ticker="XYZ",
        )
        
        result = parse_response(response)
        
        assert result["status"] == "error"
        assert result["error_code"] == "WATCH_NOT_FOUND"


# ============================================================================
# Admin Client Tools Tests
# ============================================================================


class TestAdminClientTools:
    """Tests for admin-only client tools"""

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_defunct_client_access_denied(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)

        tool_fn = get_tool_fn(mcp_server, "defunct_client")
        response = tool_fn(client_guid="client-123")
        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "ACCESS_DENIED"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_defunct_client_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        mock_permitted_groups.return_value = ["admin"]
        register_client_tools(mcp_server, mock_graph_index)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "client_guid": "client-123",
            "status": "defunct",
            "defunct_at": "2026-01-01T00:00:00Z",
        }
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session

        tool_fn = get_tool_fn(mcp_server, "defunct_client")
        response = tool_fn(client_guid="client-123", reason="merged")
        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["status"] == "defunct"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_restore_client_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        mock_permitted_groups.return_value = ["admin"]
        register_client_tools(mcp_server, mock_graph_index)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "client_guid": "client-123",
            "status": "active",
        }
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session

        tool_fn = get_tool_fn(mcp_server, "restore_client")
        response = tool_fn(client_guid="client-123")
        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["status"] == "active"

    @patch('app.tools.client_tools.resolve_permitted_groups')
    def test_delete_client_access_denied(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        mock_permitted_groups.return_value = [TEST_GROUP]
        register_client_tools(mcp_server, mock_graph_index)

        tool_fn = get_tool_fn(mcp_server, "delete_client")
        response = tool_fn(client_guid="client-123")
        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "ACCESS_DENIED"
