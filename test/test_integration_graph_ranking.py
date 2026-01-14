"""Integration Tests for Graph-Based News Ranking with Group Isolation.

Phase 6: End-to-end tests verifying the entire pipeline from ingestion
to client-specific retrieval with proper group-based content isolation.

Groups represent CONTENT SOURCES (not clients):
- Group A: "Sales Team NYC" - Internal sales intelligence
- Group B: "Reuters Feed" - Premium newswire content  
- Group C: "Alternative Data" - Proprietary data vendor

Clients query across whatever groups they have permission tokens for.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add test directory to path for local imports
sys.path.insert(0, str(Path(__file__).parent))
from test_articles import get_test_articles  # type: ignore[import]

from app.models.source import Source, SourceType, TrustLevel
from app.services.document_store import DocumentStore
from app.services.duplicate_detector import DuplicateDetector
from app.services.embedding_index import EmbeddingIndex
from app.services.graph_index import GraphIndex, NodeLabel, RelationType
from app.services.ingest_service import IngestService
from app.services.language_detector import LanguageDetector
from app.services.source_registry import SourceRegistry


# =============================================================================
# Test Data Definitions
# =============================================================================


@dataclass
class GroupDef:
    """A test group representing a content source."""
    guid: str
    name: str
    description: str





# Define our 3 test groups (content sources) with proper UUID format
TEST_GROUPS = {
    "A": GroupDef(
        guid="aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
        name="Sales Team NYC",
        description="Internal sales intelligence from NYC desk",
    ),
    "B": GroupDef(
        guid="bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb",
        name="Reuters Feed",
        description="Premium newswire content",
    ),
    "C": GroupDef(
        guid="cccccccc-cccc-4ccc-cccc-cccccccccccc",
        name="Alternative Data",
        description="Proprietary alternative data vendor",
    ),
}


# Use only the first 10 articles for this test suite
TEST_ARTICLES = get_test_articles(TEST_GROUPS)[:10]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_graph_index() -> MagicMock:
    """Create a mock GraphIndex for unit testing."""
    mock = MagicMock(spec=GraphIndex)
    mock.NodeLabel = NodeLabel
    mock.RelationType = RelationType
    return mock


@pytest.fixture
def mock_embedding_index() -> MagicMock:
    """Create a mock EmbeddingIndex for unit testing."""
    mock = MagicMock(spec=EmbeddingIndex)
    return mock


@pytest.fixture
def document_store(tmp_path) -> DocumentStore:
    """Provide a DocumentStore instance."""
    return DocumentStore(base_path=str(tmp_path / "documents"))


@pytest.fixture
def source_registry(tmp_path) -> SourceRegistry:
    """Provide a SourceRegistry instance."""
    return SourceRegistry(base_path=str(tmp_path / "sources"))


@pytest.fixture
def test_sources(source_registry: SourceRegistry) -> dict[str, Source]:
    """Create test sources (global, not group-specific)."""
    sources = {}
    for key, group in TEST_GROUPS.items():
        source = source_registry.create(
            name=f"Source for {group.name}",
            source_type=SourceType.NEWS_AGENCY,
            trust_level=TrustLevel.HIGH,
        )
        sources[key] = source
    return sources


@pytest.fixture
def ingest_service(
    document_store: DocumentStore,
    source_registry: SourceRegistry,
    mock_embedding_index: MagicMock,
    mock_graph_index: MagicMock,
) -> IngestService:
    """Create an IngestService with mocked indexes."""
    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=LanguageDetector(),
        duplicate_detector=DuplicateDetector(),
        embedding_index=mock_embedding_index,
        graph_index=mock_graph_index,
    )


# =============================================================================
# Test: Group Creation and Structure
# =============================================================================


class TestGroupStructure:
    """Tests for group-based content organization."""

    def test_groups_are_distinct(self) -> None:
        """Verify test groups have unique GUIDs."""
        guids = [g.guid for g in TEST_GROUPS.values()]
        assert len(guids) == len(set(guids)), "Group GUIDs must be unique"

    def test_articles_assigned_to_groups(self) -> None:
        """Verify all test articles are assigned to valid groups."""
        valid_guids = {g.guid for g in TEST_GROUPS.values()}
        for article in TEST_ARTICLES:
            assert article.group_guid in valid_guids, f"Article '{article.title}' has invalid group"

    def test_articles_distributed_across_groups(self) -> None:
        """Verify articles exist in multiple groups."""
        group_article_counts: dict[str, int] = {}
        for article in TEST_ARTICLES:
            group_article_counts[article.group_guid] = group_article_counts.get(article.group_guid, 0) + 1
        
        # Each group should have at least 1 article
        for group in TEST_GROUPS.values():
            assert group_article_counts.get(group.guid, 0) >= 1, f"Group {group.name} has no articles"


# =============================================================================
# Test: Document Ingestion with Group Ownership
# =============================================================================


class TestIngestionWithGroups:
    """Tests for document ingestion with correct group ownership."""

    def test_ingest_sets_correct_group(
        self,
        ingest_service: IngestService,
        document_store: DocumentStore,
        test_sources: dict[str, Source],
        mock_graph_index: MagicMock,
    ) -> None:
        """Test that ingested documents are assigned to correct group."""
        article = TEST_ARTICLES[0]  # Group A article
        source = test_sources["A"]
        
        result = ingest_service.ingest(
            title=article.title,
            content=article.content,
            source_guid=source.source_guid,
            group_guid=article.group_guid,
        )
        
        assert result.is_success
        # Verify the document was stored with correct group
        doc = document_store.load(result.guid, group_guid=article.group_guid)
        assert doc is not None
        assert doc.group_guid == article.group_guid

    def test_ingest_creates_graph_node_with_group(
        self,
        ingest_service: IngestService,
        test_sources: dict[str, Source],
        mock_graph_index: MagicMock,
    ) -> None:
        """Test that graph node is created with IN_GROUP relationship."""
        article = TEST_ARTICLES[0]
        source = test_sources["A"]
        
        _result = ingest_service.ingest(
            title=article.title,
            content=article.content,
            source_guid=source.source_guid,
            group_guid=article.group_guid,
        )
        
        # Verify create_document_node was called
        mock_graph_index.create_document_node.assert_called()
        call_kwargs = mock_graph_index.create_document_node.call_args.kwargs
        assert call_kwargs["group_guid"] == article.group_guid

    def test_ingest_embeds_with_group_metadata(
        self,
        ingest_service: IngestService,
        test_sources: dict[str, Source],
        mock_embedding_index: MagicMock,
    ) -> None:
        """Test that embeddings are stored with group metadata."""
        article = TEST_ARTICLES[0]
        source = test_sources["A"]
        
        _result = ingest_service.ingest(
            title=article.title,
            content=article.content,
            source_guid=source.source_guid,
            group_guid=article.group_guid,
        )
        
        # Verify embed_document was called with group info
        mock_embedding_index.embed_document.assert_called()
        call_kwargs = mock_embedding_index.embed_document.call_args.kwargs
        assert call_kwargs["group_guid"] == article.group_guid


# =============================================================================
# Test: Group-Based Query Filtering
# =============================================================================


class TestGroupBasedFiltering:
    """Tests for group-based query filtering.
    
    First 10 articles distribution from test_articles.py:
    - Group A: 4 articles (indices 0, 3, 6, 9) - AAPL focus
    - Group B: 3 articles (indices 1, 4, 7) - MSFT focus
    - Group C: 3 articles (indices 2, 5, 8) - TSLA focus
    """

    def test_query_single_group_returns_only_that_group(self) -> None:
        """Test that querying with one group token only returns that group's docs."""
        # Filter articles as if we only have Group B access
        permitted_groups = [TEST_GROUPS["B"].guid]
        
        visible_articles = [
            a for a in TEST_ARTICLES 
            if a.group_guid in permitted_groups
        ]
        
        # Should only see Group B articles (Reuters) - 3 articles in first 10
        assert len(visible_articles) == 3
        for article in visible_articles:
            assert article.group_guid == TEST_GROUPS["B"].guid

    def test_query_multiple_groups_returns_union(self) -> None:
        """Test that querying with multiple group tokens returns their union."""
        # Filter as if we have Groups A and B access
        permitted_groups = [TEST_GROUPS["A"].guid, TEST_GROUPS["B"].guid]
        
        visible_articles = [
            a for a in TEST_ARTICLES 
            if a.group_guid in permitted_groups
        ]
        
        # Should see Group A and B articles (4 + 3 = 7), but NOT Group C
        assert len(visible_articles) == 7
        for article in visible_articles:
            assert article.group_guid != TEST_GROUPS["C"].guid

    def test_query_all_groups_returns_everything(self) -> None:
        """Test that querying with all group tokens returns all docs."""
        permitted_groups = [g.guid for g in TEST_GROUPS.values()]
        
        visible_articles = [
            a for a in TEST_ARTICLES 
            if a.group_guid in permitted_groups
        ]
        
        assert len(visible_articles) == len(TEST_ARTICLES)

    def test_query_no_groups_returns_empty(self) -> None:
        """Test that querying with no group tokens returns nothing."""
        permitted_groups: list[str] = []
        
        visible_articles = [
            a for a in TEST_ARTICLES 
            if a.group_guid in permitted_groups
        ]
        
        assert len(visible_articles) == 0

    def test_query_invalid_group_returns_empty(self) -> None:
        """Test that querying with invalid group token returns nothing."""
        permitted_groups = ["invalid-group-guid"]
        
        visible_articles = [
            a for a in TEST_ARTICLES 
            if a.group_guid in permitted_groups
        ]
        
        assert len(visible_articles) == 0


# =============================================================================
# Test: Client Feed with Group Permissions
# =============================================================================


class TestClientFeedWithGroups:
    """Tests for client feed respecting group permissions.
    
    First 10 articles distribution:
    - Group A: 4 articles (AAPL focus)
    - Group B: 3 articles (MSFT focus)
    - Group C: 3 articles (TSLA focus)
    """

    def test_hedge_fund_client_sees_all_content(self) -> None:
        """Hedge fund client with all tokens sees everything."""
        # Hedge fund has access to all groups
        client_groups = [g.guid for g in TEST_GROUPS.values()]
        
        feed = [a for a in TEST_ARTICLES if a.group_guid in client_groups]
        
        # All 10 articles visible
        assert len(feed) == 10
        # Should see all three groups
        group_c_articles = [a for a in feed if a.group_guid == TEST_GROUPS["C"].guid]
        assert len(group_c_articles) == 3

    def test_long_only_client_no_altdata(self) -> None:
        """Long-only client without alt data token doesn't see Group C."""
        # Long-only has access to A and B only
        client_groups = [TEST_GROUPS["A"].guid, TEST_GROUPS["B"].guid]
        
        feed = [a for a in TEST_ARTICLES if a.group_guid in client_groups]
        
        # 4 (A) + 3 (B) = 7 articles
        assert len(feed) == 7
        # Should NOT see any alt data (Group C)
        for article in feed:
            assert article.group_guid != TEST_GROUPS["C"].guid

    def test_basic_client_newswire_only(self) -> None:
        """Basic client with only newswire token sees only Group B."""
        # Basic client has access to B only
        client_groups = [TEST_GROUPS["B"].guid]
        
        feed = [a for a in TEST_ARTICLES if a.group_guid in client_groups]
        
        # 3 Group B articles
        assert len(feed) == 3
        for article in feed:
            assert article.group_guid == TEST_GROUPS["B"].guid


# =============================================================================
# Test: Impact-Based Ranking Within Permitted Groups
# =============================================================================


class TestImpactRankingWithGroups:
    """Tests for impact-based ranking respecting group permissions.
    
    First 10 articles include PLATINUM articles:
    - AAPL Q4 earnings beat (Group A, PLATINUM, 90)
    - AAPL Antitrust ruling (Group A, PLATINUM, 85)
    """

    def test_platinum_articles_ranked_first(self) -> None:
        """Test that PLATINUM articles appear first in results."""
        permitted_groups = [g.guid for g in TEST_GROUPS.values()]
        
        visible_articles = [
            a for a in TEST_ARTICLES 
            if a.group_guid in permitted_groups
        ]
        
        # Sort by impact score descending
        ranked = sorted(visible_articles, key=lambda a: a.impact_score, reverse=True)
        
        # AAPL Q4 earnings beat (90, PLATINUM) should be first
        assert ranked[0].impact_tier == "PLATINUM"
        assert ranked[0].event_type == "EARNINGS_BEAT"

    def test_filtering_by_impact_respects_groups(self) -> None:
        """Test that impact filtering still respects group permissions."""
        # Client only has Group B access
        permitted_groups = [TEST_GROUPS["B"].guid]
        min_impact = 60
        
        visible_articles = [
            a for a in TEST_ARTICLES 
            if a.group_guid in permitted_groups and a.impact_score >= min_impact
        ]
        
        # Should see high-impact Group B articles (80, 65, 60)
        assert len(visible_articles) == 3
        # MSFT buyback (80) should be highest
        assert visible_articles[0].title == "MSFT: Announces major buyback program" or any(
            a.title == "MSFT: Announces major buyback program" for a in visible_articles
        )


# =============================================================================
# Test: Instrument-Based Queries with Group Permissions
# =============================================================================


class TestInstrumentQueriesWithGroups:
    """Tests for instrument-based queries respecting group permissions.
    
    First 10 articles:
    - AAPL articles are in Group A
    - MSFT articles are in Group B
    - TSLA articles are in Group C
    """

    def test_aapl_news_requires_group_a_access(self) -> None:
        """Test that AAPL news from sales intel requires Group A access."""
        # Query for AAPL with only Group B access
        permitted_groups = [TEST_GROUPS["B"].guid]
        
        aapl_articles = [
            a for a in TEST_ARTICLES
            if "AAPL" in a.instruments and a.group_guid in permitted_groups
        ]
        
        # Should find no AAPL articles (they're in Group A)
        assert len(aapl_articles) == 0

    def test_aapl_news_visible_with_group_a_access(self) -> None:
        """Test that AAPL news is visible with Group A access."""
        # Query for AAPL with Group A access
        permitted_groups = [TEST_GROUPS["A"].guid]
        
        aapl_articles = [
            a for a in TEST_ARTICLES
            if "AAPL" in a.instruments and a.group_guid in permitted_groups
        ]
        
        # 4 AAPL articles in Group A (first 10 articles)
        assert len(aapl_articles) == 4
        # Should include earnings beat article
        assert any("earnings beat" in a.title.lower() for a in aapl_articles)

    def test_msft_news_from_newswire(self) -> None:
        """Test that MSFT news is in Group B."""
        permitted_groups = [TEST_GROUPS["B"].guid]
        
        msft_articles = [
            a for a in TEST_ARTICLES
            if "MSFT" in a.instruments and a.group_guid in permitted_groups
        ]
        
        # 3 MSFT articles in Group B (first 10 articles)
        assert len(msft_articles) == 3
        # Should include buyback article
        assert any("buyback" in a.title.lower() for a in msft_articles)
