"""Integration tests for mandate_text in client tools

Tests verify end-to-end CRUD operations for mandate_text field.
"""

from __future__ import annotations

import uuid
import pytest

from app.services.graph_index import GraphIndex
from app.tools.client_tools import register_client_tools
from mcp.server.fastmcp import FastMCP
from unittest.mock import patch, MagicMock
import json
from typing import Any


TEST_GROUP = "test-group-mandate-text"
TEST_PUBLIC_GROUP = "public"


def with_auth_context(group: str = TEST_GROUP):
    """Decorator to mock auth context for a test function.
    
    Note: Pytest fixtures must be declared in the wrapper function signature
    so they are properly injected. The wrapper uses mandate_test_setup which
    provides a graph_index with test group/client type nodes already created.
    """
    def decorator(fn):
        # Apply patches as a context manager inside the wrapper instead of as decorators
        # This avoids the positional argument conflict with pytest fixtures
        def wrapper(mandate_test_setup, registered_tools, *args, **kwargs):
            with patch('app.tools.client_tools.resolve_write_group') as mock_write, \
                 patch('app.tools.client_tools.resolve_permitted_groups') as mock_permitted, \
                 patch('app.tools.client_tools.get_group_uuids_by_names') as mock_get_uuids:
                mock_write.return_value = group
                mock_permitted.return_value = [TEST_PUBLIC_GROUP, group]
                mock_get_uuids.return_value = [TEST_PUBLIC_GROUP, group]
                # mandate_test_setup IS the graph_index, pass it to the test as graph_index
                return fn(mandate_test_setup, registered_tools, *args, **kwargs)
        # Copy function name and docstring for pytest
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return decorator

def parse_response(response: Any) -> dict[str, Any]:
    """Parse MCP tool response to dict"""
    if hasattr(response, "__iter__"):
        for item in response:
            if hasattr(item, "text"):
                return json.loads(item.text)
    return {}


# NOTE: We use the global graph_index fixture from conftest.py which creates
# a clean Neo4j state for each test and handles connection/cleanup.


@pytest.fixture
def mandate_test_setup(graph_index: GraphIndex) -> GraphIndex:
    """Set up test group and client type nodes required for mandate_text tests.
    
    Creates:
    - Group node with TEST_GROUP guid
    - ClientType node with HEDGE_FUND code
    
    Returns the graph_index for use in tests.
    """
    from app.services.graph_index import NodeLabel
    
    # Create test group node
    graph_index.create_node(NodeLabel.GROUP, TEST_GROUP, {"name": "Test Group"})
    
    # Create client type node (used by IS_TYPE_OF relationship)
    graph_index.create_node(NodeLabel.CLIENT_TYPE, "HEDGE_FUND", {"code": "HEDGE_FUND", "name": "Hedge Fund"})
    
    return graph_index


@pytest.fixture
def mandate_text_mcp_server() -> FastMCP:
    """Create a FastMCP server for testing mandate_text"""
    return FastMCP("test-mandate-text")


@pytest.fixture
def registered_tools(mandate_text_mcp_server: FastMCP, mandate_test_setup: GraphIndex) -> dict[str, Any]:
    """Register client tools and return them.
    
    Uses mandate_test_setup to ensure group/client type nodes exist first.
    """
    register_client_tools(mandate_text_mcp_server, mandate_test_setup, query_service=MagicMock())
    return {tool.name: tool for tool in mandate_text_mcp_server._tool_manager._tools.values()}


@pytest.mark.integration
@with_auth_context()
def test_update_client_mandate_text_create(graph_index: GraphIndex, registered_tools: dict):
    """Test creating mandate_text via update_client_profile"""
    # Setup: Create client
    client_guid = str(uuid.uuid4())
    profile_guid = str(uuid.uuid4())
    
    graph_index.create_client(
        guid=client_guid,
        name="Test Mandate Client",
        client_type_code="HEDGE_FUND",
        group_guid=TEST_GROUP,
    )
    graph_index.create_client_profile(
        guid=profile_guid,
        client_guid=client_guid,
    )
    
    # Test: Add mandate_text
    mandate_text = "Our fund focuses on US technology stocks with strong ESG ratings."
    update_tool = registered_tools["update_client_profile"]
    response = update_tool.fn(
        client_guid=client_guid,
        mandate_text=mandate_text,
    )
    
    result = parse_response(response)
    
    # Verify: mandate_text in response
    assert result["status"] == "success"
    assert result["data"]["profile"]["mandate_text"] == mandate_text
    assert "mandate_text" in result["data"]["changes"]
    
    # Verify: mandate_text persisted in database
    get_tool = registered_tools["get_client_profile"]
    get_response = get_tool.fn(client_guid=client_guid)
    get_result = parse_response(get_response)
    
    assert get_result["data"]["profile"]["mandate_text"] == mandate_text


@pytest.mark.integration
@with_auth_context()
def test_update_client_mandate_text_overwrite(graph_index: GraphIndex, registered_tools: dict):
    """Test overwriting existing mandate_text"""
    # Setup: Create client with initial mandate_text
    client_guid = str(uuid.uuid4())
    profile_guid = str(uuid.uuid4())
    
    graph_index.create_client(
        guid=client_guid,
        name="Test Overwrite Client",
        client_type_code="HEDGE_FUND",
        group_guid=TEST_GROUP,
    )
    graph_index.create_client_profile(
        guid=profile_guid,
        client_guid=client_guid,
        properties={"mandate_text": "Initial mandate text"},
    )
    
    # Test: Overwrite mandate_text
    new_mandate = "Updated fund mandate with different strategy."
    update_tool = registered_tools["update_client_profile"]
    response = update_tool.fn(
        client_guid=client_guid,
        mandate_text=new_mandate,
    )
    
    result = parse_response(response)
    
    # Verify: New mandate_text in response
    assert result["status"] == "success"
    assert result["data"]["profile"]["mandate_text"] == new_mandate
    
    # Verify: Old mandate_text replaced
    get_tool = registered_tools["get_client_profile"]
    get_response = get_tool.fn(client_guid=client_guid)
    get_result = parse_response(get_response)
    
    assert get_result["data"]["profile"]["mandate_text"] == new_mandate
    assert get_result["data"]["profile"]["mandate_text"] != "Initial mandate text"


@pytest.mark.integration
@with_auth_context()
def test_update_client_mandate_text_clear(graph_index: GraphIndex, registered_tools: dict):
    """Test clearing mandate_text with empty string"""
    # Setup: Create client with mandate_text
    client_guid = str(uuid.uuid4())
    profile_guid = str(uuid.uuid4())
    
    graph_index.create_client(
        guid=client_guid,
        name="Test Clear Client",
        client_type_code="HEDGE_FUND",
        group_guid=TEST_GROUP,
    )
    graph_index.create_client_profile(
        guid=profile_guid,
        client_guid=client_guid,
        properties={"mandate_text": "Existing mandate text"},
    )
    
    # Test: Clear mandate_text with empty string
    update_tool = registered_tools["update_client_profile"]
    response = update_tool.fn(
        client_guid=client_guid,
        mandate_text="",
    )
    
    result = parse_response(response)
    
    # Verify: Empty mandate_text in response
    assert result["status"] == "success"
    assert result["data"]["profile"]["mandate_text"] == ""
    
    # Verify: mandate_text cleared in database
    get_tool = registered_tools["get_client_profile"]
    get_response = get_tool.fn(client_guid=client_guid)
    get_result = parse_response(get_response)
    
    assert get_result["data"]["profile"]["mandate_text"] == ""


@pytest.mark.integration
@with_auth_context()
def test_update_client_mandate_text_preserve_on_omit(graph_index: GraphIndex, registered_tools: dict):
    """Test that omitting mandate_text preserves existing value"""
    # Setup: Create client with mandate_text
    client_guid = str(uuid.uuid4())
    profile_guid = str(uuid.uuid4())
    original_mandate = "Original mandate text that should be preserved"
    
    graph_index.create_client(
        guid=client_guid,
        name="Test Preserve Client",
        client_type_code="HEDGE_FUND",
        group_guid=TEST_GROUP,
    )
    graph_index.create_client_profile(
        guid=profile_guid,
        client_guid=client_guid,
        properties={"mandate_text": original_mandate},
    )
    
    # Test: Update different field, omit mandate_text
    update_tool = registered_tools["update_client_profile"]
    response = update_tool.fn(
        client_guid=client_guid,
        mandate_type="equity_long_short",
    )
    
    result = parse_response(response)
    
    # Verify: mandate_text still present and unchanged
    assert result["status"] == "success"
    assert result["data"]["profile"]["mandate_text"] == original_mandate
    assert "mandate_text" not in result["data"]["changes"]
    assert "mandate_type" in result["data"]["changes"]


@pytest.mark.integration
@with_auth_context()
def test_update_client_mandate_text_length_validation(graph_index: GraphIndex, registered_tools: dict):
    """Test mandate_text length validation (max 5000 chars)"""
    # Setup: Create client
    client_guid = str(uuid.uuid4())
    profile_guid = str(uuid.uuid4())
    
    graph_index.create_client(
        guid=client_guid,
        name="Test Validation Client",
        client_type_code="HEDGE_FUND",
        group_guid=TEST_GROUP,
    )
    graph_index.create_client_profile(
        guid=profile_guid,
        client_guid=client_guid,
    )
    
    # Test: Exceed 5000 character limit
    too_long_mandate = "x" * 5001
    update_tool = registered_tools["update_client_profile"]
    response = update_tool.fn(
        client_guid=client_guid,
        mandate_text=too_long_mandate,
    )
    
    result = parse_response(response)
    
    # Verify: Error returned
    assert result["status"] == "error"
    assert result["error_code"] == "MANDATE_TEXT_TOO_LONG"
    assert "5000" in result["message"]


@pytest.mark.integration
@with_auth_context()
def test_get_client_profile_includes_mandate_text(graph_index: GraphIndex, registered_tools: dict):
    """Test that get_client_profile returns mandate_text"""
    # Setup: Create client with mandate_text
    client_guid = str(uuid.uuid4())
    profile_guid = str(uuid.uuid4())
    mandate_text = "Test mandate for profile retrieval"
    
    graph_index.create_client(
        guid=client_guid,
        name="Test Get Profile Client",
        client_type_code="HEDGE_FUND",
        group_guid=TEST_GROUP,
    )
    graph_index.create_client_profile(
        guid=profile_guid,
        client_guid=client_guid,
        properties={"mandate_text": mandate_text},
    )
    
    # Test: Get client profile
    get_tool = registered_tools["get_client_profile"]
    response = get_tool.fn(client_guid=client_guid)
    
    result = parse_response(response)
    
    # Verify: mandate_text in response
    assert result["status"] == "success"
    assert result["data"]["profile"]["mandate_text"] == mandate_text


@pytest.mark.integration
@with_auth_context()
def test_get_client_profile_null_mandate_text(graph_index: GraphIndex, registered_tools: dict):
    """Test that get_client_profile handles null mandate_text gracefully"""
    # Setup: Create client without mandate_text
    client_guid = str(uuid.uuid4())
    profile_guid = str(uuid.uuid4())
    
    graph_index.create_client(
        guid=client_guid,
        name="Test Null Mandate Client",
        client_type_code="HEDGE_FUND",
        group_guid=TEST_GROUP,
    )
    graph_index.create_client_profile(
        guid=profile_guid,
        client_guid=client_guid,
    )
    
    # Test: Get client profile
    get_tool = registered_tools["get_client_profile"]
    response = get_tool.fn(client_guid=client_guid)
    
    result = parse_response(response)
    
    # Verify: mandate_text is null or empty
    assert result["status"] == "success"
    assert result["data"]["profile"]["mandate_text"] in [None, ""]


    @pytest.mark.integration
    @with_auth_context()
    def test_get_client_profile_includes_mandate_embedding_len(graph_index: GraphIndex, registered_tools: dict):
        """Test that get_client_profile returns mandate_embedding_len when embedding exists."""
        client_guid = str(uuid.uuid4())
        profile_guid = str(uuid.uuid4())

        graph_index.create_client(
            guid=client_guid,
            name="Test Embedding Len Client",
            client_type_code="HEDGE_FUND",
            group_guid=TEST_GROUP,
        )
        graph_index.create_client_profile(
            guid=profile_guid,
            client_guid=client_guid,
            properties={"mandate_embedding": [0.1, 0.2, 0.3]},
        )

        get_tool = registered_tools["get_client_profile"]
        response = get_tool.fn(client_guid=client_guid)
        result = parse_response(response)

        assert result["status"] == "success"
        assert result["data"]["profile"]["mandate_embedding_len"] == 3
