"""Deterministic tests for mandate embedding persistence logic (Milestone M4).

We mock `create_llm_service` so tests don't make real API calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.graph_index import GraphIndex, NodeLabel
from app.tools.client_tools import register_client_tools
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def mcp_server() -> FastMCP:
    return FastMCP("test-mandate-embedding")


@pytest.fixture
def tools(mcp_server: FastMCP, graph_index: GraphIndex) -> dict[str, object]:
    register_client_tools(mcp_server, graph_index, query_service=MagicMock())
    return {tool.name: tool for tool in mcp_server._tool_manager._tools.values()}


@pytest.mark.integration
def test_update_client_profile_sets_mandate_embedding(graph_index: GraphIndex, tools: dict[str, object]) -> None:
    # Setup required nodes
    graph_index.create_node(NodeLabel.GROUP, "public", {"name": "public"})
    graph_index.create_node(NodeLabel.CLIENT_TYPE, "HEDGE_FUND", {"code": "HEDGE_FUND"})

    client_guid = str(uuid.uuid4())
    profile_guid = str(uuid.uuid4())
    graph_index.create_client(guid=client_guid, name="Test", client_type_code="HEDGE_FUND", group_guid="public")
    graph_index.create_client_profile(guid=profile_guid, client_guid=client_guid)

    fake_llm = MagicMock()
    fake_llm.is_available = True
    fake_llm.generate_embedding.return_value = [0.1, 0.2, 0.3]
    fake_llm.__enter__.return_value = fake_llm
    fake_llm.__exit__.return_value = False

    with patch("app.tools.client_tools.resolve_permitted_groups", return_value=["public"]), \
         patch("app.tools.client_tools.get_group_uuids_by_names", return_value=["public"]), \
         patch("app.services.llm_service.create_llm_service", return_value=fake_llm), \
         patch("app.services.mandate_enrichment.extract_themes_from_mandate") as mock_extract:
        mock_extract.return_value.success = True
        mock_extract.return_value.themes = ["ai"]

        update_tool = tools["update_client_profile"]
        update_tool.fn(client_guid=client_guid, mandate_text="We invest in AI")

    # Verify embedding persisted
    with graph_index._get_session() as session:
        record = session.run(
            "MATCH (cp:ClientProfile {guid: $guid}) RETURN cp.mandate_embedding AS emb",
            guid=profile_guid,
        ).single()
        assert record is not None
        assert record.get("emb") == [0.1, 0.2, 0.3]
