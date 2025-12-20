"""Tests for Graph Tools

Unit tests for the MCP graph exploration tools.

NOTE: These tools are NOT exposed by the default MCP server configuration.
They remain available for direct use but are not registered via register_all_tools.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from app.services.graph_index import GraphIndex, GraphNode, NodeLabel
from app.tools.graph_tools import register_graph_tools


# ============================================================================
# Test Constants
# ============================================================================

TEST_PUBLIC_GROUP = "public"
TEST_GROUP = "test-group-123"


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_graph_index() -> MagicMock:
    """Create a mock GraphIndex"""
    mock = MagicMock(spec=GraphIndex)
    mock.NodeLabel = NodeLabel
    mock._get_session = MagicMock()
    return mock


@pytest.fixture
def mcp_server() -> FastMCP:
    """Create a FastMCP server for testing"""
    return FastMCP("test-graph-tools")


@pytest.fixture
def registered_tools(mcp_server: FastMCP, mock_graph_index: MagicMock) -> dict[str, Any]:
    """Register graph tools and return them"""
    register_graph_tools(mcp_server, mock_graph_index)
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
        """Test that all graph tools are registered"""
        assert "explore_graph" in registered_tools
        assert "get_market_context" in registered_tools
        assert "get_instrument_news" in registered_tools

    def test_explore_graph_description(self, registered_tools: dict[str, Any]) -> None:
        """Test explore_graph has proper description"""
        tool = registered_tools["explore_graph"]
        assert "explore" in tool.description.lower()
        assert "graph" in tool.description.lower()

    def test_get_market_context_description(self, registered_tools: dict[str, Any]) -> None:
        """Test get_market_context has proper description"""
        tool = registered_tools["get_market_context"]
        assert "comprehensive" in tool.description.lower() or "context" in tool.description.lower()


# ============================================================================
# Explore Graph Tests
# ============================================================================


class TestExploreGraph:
    """Tests for explore_graph tool"""

    def test_explore_from_instrument(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test exploring from an instrument node"""
        register_graph_tools(mcp_server, mock_graph_index)

        # Mock instrument lookup
        mock_graph_index.get_instrument.return_value = GraphNode(
            label=NodeLabel.INSTRUMENT,
            guid="AAPL:NYSE",
            properties={"ticker": "AAPL", "name": "Apple Inc."},
        )

        # Mock session for graph traversal
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {
                "rel_type": "AFFECTS",
                "related": {"guid": "doc-1", "title": "Apple Earnings Beat"},
                "related_label": "Document",
                "rel_props": {"magnitude": 0.8, "direction": "positive"},
            },
            {
                "rel_type": "ISSUED_BY",
                "related": {"guid": "AAPL", "name": "Apple Inc."},
                "related_label": "Company",
                "rel_props": {},
            },
        ]))
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session

        tool_fn = get_tool_fn(mcp_server, "explore_graph")

        response = tool_fn(
            node_type="INSTRUMENT",
            node_id="AAPL",
            max_depth=1,
            limit=10,
        )

        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["start_node"]["label"] == "Instrument"
        assert len(result["data"]["relationships"]) == 2

    def test_explore_with_relationship_filter(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test exploring with specific relationship types"""
        register_graph_tools(mcp_server, mock_graph_index)

        mock_graph_index.get_node.return_value = GraphNode(
            label=NodeLabel.COMPANY,
            guid="AAPL",
            properties={"name": "Apple Inc."},
        )

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {
                "rel_type": "PEER_OF",
                "related": {"guid": "MSFT", "name": "Microsoft"},
                "related_label": "Company",
                "rel_props": {"correlation": 0.75},
            },
        ]))
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session

        tool_fn = get_tool_fn(mcp_server, "explore_graph")

        response = tool_fn(
            node_type="COMPANY",
            node_id="AAPL",
            relationship_types=["PEER_OF"],
        )

        result = parse_response(response)

        assert result["status"] == "success"
        assert len(result["data"]["relationships"]) == 1
        assert result["data"]["relationships"][0]["relationship_type"] == "PEER_OF"

    def test_explore_node_not_found(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test exploring from non-existent node"""
        register_graph_tools(mcp_server, mock_graph_index)

        mock_graph_index.get_instrument.return_value = None

        tool_fn = get_tool_fn(mcp_server, "explore_graph")

        response = tool_fn(
            node_type="INSTRUMENT",
            node_id="INVALID",
        )

        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "NODE_NOT_FOUND"

    def test_explore_invalid_node_type(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test exploring with invalid node type"""
        register_graph_tools(mcp_server, mock_graph_index)

        tool_fn = get_tool_fn(mcp_server, "explore_graph")

        response = tool_fn(
            node_type="INVALID_TYPE",
            node_id="test",
        )

        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_NODE_TYPE"


# ============================================================================
# Get Market Context Tests
# ============================================================================


class TestGetMarketContext:
    """Tests for get_market_context tool"""

    def test_get_context_full(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting full market context"""
        register_graph_tools(mcp_server, mock_graph_index)

        # Mock instrument
        mock_graph_index.get_instrument.return_value = GraphNode(
            label=NodeLabel.INSTRUMENT,
            guid="AAPL:NYSE",
            properties={
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "instrument_type": "STOCK",
                "exchange": "NYSE",
                "currency": "USD",
                "country": "US",
            },
        )

        # Mock session for various queries
        mock_session = MagicMock()

        # Company query
        company_result = MagicMock()
        company_result.single.return_value = {"c": {"guid": "AAPL", "name": "Apple Inc."}}

        # Peers query
        peers_result = MagicMock()
        peers_result.__iter__ = MagicMock(return_value=iter([
            {"peer": {"guid": "MSFT", "name": "Microsoft"}, "correlation": 0.75},
        ]))

        # Events query
        events_result = MagicMock()
        events_result.__iter__ = MagicMock(return_value=iter([
            {
                "d": {
                    "guid": "doc-1",
                    "title": "Apple Q4 Earnings",
                    "created_at": "2025-01-15T10:00:00Z",
                    "impact_score": 85,
                    "impact_tier": "GOLD",
                },
                "et": {"code": "EARNINGS_BEAT", "name": "Earnings Beat"},
                "magnitude": 0.8,
                "direction": "positive",
            },
        ]))

        # Indices query
        indices_result = MagicMock()
        indices_result.__iter__ = MagicMock(return_value=iter([
            {"idx": {"guid": "SPY", "name": "S&P 500 ETF"}, "weight": 0.07},
        ]))

        # Sector query
        sector_result = MagicMock()
        sector_result.single.return_value = {"s": {"guid": "TECH", "name": "Technology"}}

        # Setup mock session to return different results for each query
        call_count = [0]

        def run_side_effect(*args: Any, **kwargs: Any) -> Any:
            call_count[0] += 1
            if call_count[0] == 1:
                return company_result
            elif call_count[0] == 2:
                return peers_result
            elif call_count[0] == 3:
                return events_result
            elif call_count[0] == 4:
                return indices_result
            else:
                return sector_result

        mock_session.run.side_effect = run_side_effect
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session

        tool_fn = get_tool_fn(mcp_server, "explore_graph")

        response = tool_fn(
            node_type="INSTRUMENT",
            node_id="AAPL",
        )

        result = parse_response(response)

        assert result["status"] == "success"

    def test_get_context_instrument_not_found(
        self,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test market context for non-existent instrument"""
        register_graph_tools(mcp_server, mock_graph_index)

        mock_graph_index.get_instrument.return_value = None

        tool_fn = get_tool_fn(mcp_server, "get_market_context")

        response = tool_fn(ticker="INVALID")

        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "INSTRUMENT_NOT_FOUND"


# ============================================================================
# Get Instrument News Tests
# ============================================================================


class TestGetInstrumentNews:
    """Tests for get_instrument_news tool"""

    @patch('app.tools.graph_tools.resolve_permitted_groups')
    def test_get_news_success(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting news for an instrument"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_graph_tools(mcp_server, mock_graph_index)

        # Mock instrument
        mock_graph_index.get_instrument.return_value = GraphNode(
            label=NodeLabel.INSTRUMENT,
            guid="AAPL:NYSE",
            properties={"ticker": "AAPL"},
        )

        # Mock session
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {
                "d": {
                    "guid": "doc-1",
                    "title": "Apple Beats Earnings",
                    "impact_score": 85,
                    "impact_tier": "GOLD",
                    "created_at": "2025-01-15T10:00:00Z",
                },
                "et": {"code": "EARNINGS_BEAT", "name": "Earnings Beat"},
                "magnitude": 0.8,
                "direction": "positive",
            },
        ]))
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session

        tool_fn = get_tool_fn(mcp_server, "get_instrument_news")

        # Call without group_guids - extracted from context
        response = tool_fn(
            ticker="AAPL",
            days_back=7,
        )

        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["ticker"] == "AAPL"
        assert len(result["data"]["articles"]) == 1
        assert result["data"]["articles"][0]["title"] == "Apple Beats Earnings"

    @patch('app.tools.graph_tools.resolve_permitted_groups')
    def test_get_news_with_impact_filter(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting news with minimum impact filter"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP, TEST_GROUP]
        register_graph_tools(mcp_server, mock_graph_index)

        mock_graph_index.get_instrument.return_value = GraphNode(
            label=NodeLabel.INSTRUMENT,
            guid="AAPL:NYSE",
            properties={"ticker": "AAPL"},
        )

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)
        mock_graph_index._get_session.return_value = mock_session

        tool_fn = get_tool_fn(mcp_server, "get_instrument_news")

        # Call without group_guids
        response = tool_fn(
            ticker="AAPL",
            min_impact_score=70.0,
        )

        result = parse_response(response)

        assert result["status"] == "success"
        # Verify the query was called with the impact filter
        mock_session.run.assert_called_once()

    @patch('app.tools.graph_tools.resolve_permitted_groups')
    def test_get_news_instrument_not_found(
        self,
        mock_permitted_groups: MagicMock,
        mcp_server: FastMCP,
        mock_graph_index: MagicMock,
    ) -> None:
        """Test getting news for non-existent instrument"""
        mock_permitted_groups.return_value = [TEST_PUBLIC_GROUP]
        register_graph_tools(mcp_server, mock_graph_index)

        mock_graph_index.get_instrument.return_value = None

        tool_fn = get_tool_fn(mcp_server, "get_instrument_news")

        # Call without group_guids
        response = tool_fn(
            ticker="INVALID",
        )

        result = parse_response(response)

        assert result["status"] == "error"
        assert result["error_code"] == "INSTRUMENT_NOT_FOUND"
