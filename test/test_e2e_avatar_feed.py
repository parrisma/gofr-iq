"""End-to-End Avatar Feed Test -- Live LLM Ingestion.

Step 15 of the avatar-feed-gap-plan. Ingests a real article through the
full LLM pipeline and verifies the avatar feed returns it correctly.

Requirements:
- Run via ./scripts/run_tests.sh (sets up test infrastructure)
- GOFR_IQ_OPENROUTER_API_KEY must be set (~$0.02 per run)
- Neo4j, ChromaDB, and Vault test containers must be running

What this test proves:
1. Real LLM extracts NXS ticker and ai/semiconductor themes from a clear article
2. All extracted themes are in VALID_THEMES (Step 10 enforcement)
3. AFFECTS edge to NXS is created in Neo4j
4. Avatar feed MAINTENANCE channel surfaces the article for a client holding NXS
"""

import json
import os
import pathlib
import uuid

import pytest

from app.models.themes import VALID_THEMES
from app.services.document_store import DocumentStore
from app.services.embedding_index import EmbeddingIndex
from app.services.graph_index import GraphIndex, NodeLabel
from app.services.ingest_service import IngestService
from app.services.llm_service import LLMSettings, create_llm_service
from app.services.query_service import QueryService
from app.services.source_registry import SourceRegistry


# =============================================================================
# Constants
# =============================================================================

TEST_ARTICLE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "simulation"
    / "test_data"
    / "e2e_nxs_earnings.txt"
)

# Deterministic GUIDs for test entities (valid UUID format)
TEST_GROUP_GUID = "e2e00000-0000-0000-0000-000000000001"
TEST_CLIENT_GUID = "e2e00000-0000-0000-0000-000000000002"
TEST_PROFILE_GUID = "e2e00000-0000-0000-0000-000000000003"
TEST_PORTFOLIO_GUID = "e2e00000-0000-0000-0000-000000000004"
TEST_SOURCE_GUID = "e2e00000-0000-0000-0000-000000000005"
TEST_CLIENT_TYPE_CODE = "HEDGE_FUND"
TEST_NXS_INSTRUMENT_GUID = "NXS:NASDAQ"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def openrouter_api_key() -> str:
    """Skip if no OpenRouter key -- these tests cost real money."""
    key = os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
    if not key:
        pytest.skip("GOFR_IQ_OPENROUTER_API_KEY not set (live LLM test)")
    return key


@pytest.fixture
def e2e_graph_index(neo4j_config: dict[str, str | int]):
    """Graph index with a seeded universe for the e2e test.

    Seeds: Group, ClientType, Client, Profile, Portfolio, Instrument (NXS),
    HOLDS relationship, and mandate_themes on the profile.
    Cleans up after the test.
    """
    index = GraphIndex(
        uri=str(neo4j_config["uri"]),
        password=str(neo4j_config["password"]),
    )
    index.clear()
    index.init_schema()

    # -- Group --
    index.create_node(NodeLabel.GROUP, TEST_GROUP_GUID, {"name": "e2e-test-group"})

    # -- Client type --
    index.create_client_type(TEST_CLIENT_TYPE_CODE, "Hedge Fund")

    # -- Client (linked to group) --
    index.create_client(
        guid=TEST_CLIENT_GUID,
        name="E2E Test Fund",
        client_type_code=TEST_CLIENT_TYPE_CODE,
        group_guid=TEST_GROUP_GUID,
    )

    # -- Profile (with mandate_themes for ai + semiconductor) --
    index.create_client_profile(
        guid=TEST_PROFILE_GUID,
        client_guid=TEST_CLIENT_GUID,
        mandate_type="equity_long_short",
        horizon="medium",
        properties={"mandate_themes": json.dumps(["ai", "semiconductor"])},
    )

    # -- Instrument (NXS) --
    index.create_instrument(
        ticker="NXS",
        name="Nexus Software",
        instrument_type="STOCK",
        exchange="NASDAQ",
    )

    # -- Portfolio + Holding --
    index.create_portfolio(guid=TEST_PORTFOLIO_GUID, client_guid=TEST_CLIENT_GUID)
    index.add_holding(
        portfolio_guid=TEST_PORTFOLIO_GUID,
        instrument_guid=TEST_NXS_INSTRUMENT_GUID,
        weight=0.25,
    )

    # -- Source node (so PRODUCED_BY edge can be created) --
    index.create_source_node(
        source_guid=TEST_SOURCE_GUID,
        name="E2E Test Wire",
        source_type="NEWS_AGENCY",
    )

    yield index

    try:
        index.clear()
    except Exception:
        pass
    finally:
        index.close()


@pytest.fixture
def e2e_source_registry() -> SourceRegistry:
    """Source registry that knows about the test source."""
    from app.models import SourceType
    from app.services.source_registry import SourceNotFoundError

    data_dir = os.environ.get("GOFR_AUTH_DATA_DIR", "data/auth")
    registry = SourceRegistry(data_dir)
    # Create the source if it doesn't already exist
    try:
        registry.get(TEST_SOURCE_GUID)
    except SourceNotFoundError:
        registry.create(
            name="E2E Test Wire",
            source_type=SourceType.NEWS_AGENCY,
            source_guid=TEST_SOURCE_GUID,
        )
    return registry


@pytest.fixture
def e2e_embedding_index(chromadb_config: dict[str, str | int]) -> EmbeddingIndex:
    """Embedding index with unique collection for this test."""
    collection = f"e2e_avatar_{uuid.uuid4().hex[:8]}"
    return EmbeddingIndex(
        host=str(chromadb_config["host"]),
        port=int(chromadb_config["port"]),
        collection_name=collection,
    )


@pytest.fixture
def e2e_ingest_service(
    openrouter_api_key: str,
    e2e_graph_index: GraphIndex,
    e2e_embedding_index: EmbeddingIndex,
    e2e_source_registry: SourceRegistry,
) -> IngestService:
    """IngestService wired to real LLM + real Neo4j + real ChromaDB."""
    chat_model = os.environ.get(
        "GOFR_IQ_LLM_MODEL", "meta-llama/llama-3.1-70b-instruct"
    )
    settings = LLMSettings(api_key=openrouter_api_key, chat_model=chat_model)
    llm = create_llm_service(settings=settings)

    storage_dir = os.environ.get("GOFR_IQ_STORAGE_DIR", "data/storage")
    document_store = DocumentStore(storage_dir)

    return IngestService(
        document_store=document_store,
        source_registry=e2e_source_registry,
        llm_service=llm,
        embedding_index=e2e_embedding_index,
        graph_index=e2e_graph_index,
    )


@pytest.fixture
def e2e_query_service(
    e2e_graph_index: GraphIndex,
    e2e_embedding_index: EmbeddingIndex,
    e2e_source_registry: SourceRegistry,
) -> QueryService:
    """QueryService wired to real Neo4j + real ChromaDB."""
    storage_dir = os.environ.get("GOFR_IQ_STORAGE_DIR", "data/storage")
    document_store = DocumentStore(storage_dir)

    return QueryService(
        embedding_index=e2e_embedding_index,
        document_store=document_store,
        source_registry=e2e_source_registry,
        graph_index=e2e_graph_index,
    )


# =============================================================================
# Tests
# =============================================================================


class TestLiveAvatarFeed:
    """End-to-end: ingest real article -> query avatar feed -> verify."""

    def test_ingest_and_avatar_feed(
        self,
        e2e_ingest_service: IngestService,
        e2e_query_service: QueryService,
        e2e_graph_index: GraphIndex,
    ) -> None:
        """Ingest NXS earnings article through real LLM and verify avatar feed.

        Asserts:
        1. Ingestion succeeds
        2. All themes on the Document node are in VALID_THEMES
        3. AFFECTS edge to NXS exists
        4. Avatar feed MAINTENANCE channel contains the article
        """
        # -- Read test article --
        content = TEST_ARTICLE_PATH.read_text()
        assert len(content) > 100, "Test article should not be empty"

        # -- Step A: Ingest through real LLM pipeline --
        result = e2e_ingest_service.ingest(
            title="NXS Reports Record Q4 Earnings on AI Chip Demand",
            content=content,
            source_guid=TEST_SOURCE_GUID,
            group_guid=TEST_GROUP_GUID,
            language="en",
        )

        assert result.status.value == "success" or str(result.status) == "success", (
            f"Ingest failed: {result}"
        )
        doc_guid = result.guid
        assert doc_guid, "Ingest should return a document GUID"

        # -- Step B: Verify themes are all in VALID_THEMES --
        with e2e_graph_index._get_session() as session:
            rec = session.run(
                "MATCH (d:Document {guid: $guid}) RETURN d.themes AS themes",
                guid=doc_guid,
            ).single()

        assert rec is not None, f"Document {doc_guid} not found in Neo4j"
        raw_themes = rec["themes"]
        if isinstance(raw_themes, str):
            themes = json.loads(raw_themes)
        elif raw_themes is None:
            themes = []
        else:
            themes = list(raw_themes)

        bad_themes = [t for t in themes if t not in VALID_THEMES]
        assert not bad_themes, (
            f"Out-of-vocab themes on Document node: {bad_themes}. "
            f"All themes: {themes}"
        )
        # Should have extracted at least one relevant theme
        assert len(themes) > 0, "LLM should extract at least one theme from NXS article"

        # Log for manual inspection (Step 15.3)
        print(f"\n[E2E] doc_guid: {doc_guid}")
        print(f"[E2E] themes: {themes}")

        # -- Step C: Verify AFFECTS edge to NXS --
        with e2e_graph_index._get_session() as session:
            affects_rec = session.run(
                """
                MATCH (d:Document {guid: $guid})-[:AFFECTS]->(i:Instrument)
                RETURN collect(i.ticker) AS tickers
                """,
                guid=doc_guid,
            ).single()

        affected_tickers = affects_rec["tickers"] if affects_rec else []
        print(f"[E2E] affected_tickers: {affected_tickers}")

        assert "NXS" in affected_tickers, (
            f"AFFECTS edge to NXS missing. Affected tickers: {affected_tickers}"
        )

        # -- Step D: Query avatar feed for the test client --
        feed = e2e_query_service.get_client_avatar_feed(
            client_guid=TEST_CLIENT_GUID,
            group_guids=[TEST_GROUP_GUID],
            limit=20,
            time_window_hours=720,  # Wide window for test
        )

        maintenance_guids = [item.document_guid for item in feed.maintenance]
        print(f"[E2E] maintenance items: {len(feed.maintenance)}")
        for item in feed.maintenance:
            print(f"  - {item.title} (score={item.relevance_score:.2f}, tickers={item.affected_instruments})")

        assert doc_guid in maintenance_guids, (
            f"Document {doc_guid} not in MAINTENANCE channel. "
            f"Got {len(feed.maintenance)} items: {maintenance_guids}"
        )

        # -- Step E: Verify the maintenance item has correct metadata --
        doc_item = next(i for i in feed.maintenance if i.document_guid == doc_guid)
        assert "NXS" in doc_item.affected_instruments, (
            f"NXS not in affected_instruments: {doc_item.affected_instruments}"
        )
        assert doc_item.channel.upper() == "MAINTENANCE"

        # Log opportunity channel too for awareness
        if feed.opportunity:
            print(f"[E2E] opportunity items: {len(feed.opportunity)}")
            for item in feed.opportunity:
                print(f"  - {item.title} (themes={item.themes})")
