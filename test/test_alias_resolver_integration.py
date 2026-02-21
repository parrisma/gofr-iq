"""Integration tests for AliasResolver (Milestone M2).

These tests use the real Neo4j test container (via neo4j_config fixture) but do
not require LLM calls.
"""

from __future__ import annotations

import pytest

from app.services.alias_resolver import AliasResolver
from app.services.graph_index import GraphIndex, NodeLabel
from app.services.ingest_service import IngestService


@pytest.fixture
def graph_index(neo4j_config: dict[str, str | int]) -> GraphIndex:
    index = GraphIndex(
        uri=str(neo4j_config["uri"]),
        password=str(neo4j_config["password"]),
    )
    index.init_schema()
    return index


def test_alias_resolver_resolves_to_canonical_guid(graph_index: GraphIndex) -> None:
    # Seed canonical instrument node
    graph_index.create_node(
        NodeLabel.INSTRUMENT,
        "inst-GOOGL",
        {
            "ticker": "GOOGL",
            "name": "Alphabet Inc",
            "instrument_type": "STOCK",
            "exchange": "NASDAQ",
        },
    )

    graph_index.upsert_alias(
        value="Alphabet",
        scheme="NAME_VARIANT",
        canonical_guid="inst-GOOGL",
    )

    resolver = AliasResolver(graph_index)
    assert resolver.resolve("Alphabet", scheme="NAME_VARIANT") == "inst-GOOGL"


def test_ingest_service_uses_alias_before_autocreate(graph_index: GraphIndex) -> None:
    # Canonical instrument exists
    graph_index.create_node(
        NodeLabel.INSTRUMENT,
        "inst-GOOGL",
        {"ticker": "GOOGL", "name": "Alphabet Inc", "instrument_type": "STOCK"},
    )
    graph_index.upsert_alias(
        value="Alphabet",
        scheme="NAME_VARIANT",
        canonical_guid="inst-GOOGL",
    )

    # IngestService is only used here for _resolve_instrument_guid, so we can
    # bypass full construction.
    service = IngestService.__new__(IngestService)
    service.graph_index = graph_index
    service.alias_resolver = AliasResolver(graph_index)
    service.strict_ticker_validation = False

    with graph_index._get_session() as session:
        resolved = service._resolve_instrument_guid(
            session=session,
            ticker="ALPHABET",  # not a real ticker in graph
            name="Alphabet",
        )

    assert resolved == "inst-GOOGL"
