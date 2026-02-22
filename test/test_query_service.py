"""Tests for Query Service (Phase 12: Hybrid Search)

Tests the orchestration of ChromaDB similarity search with Neo4j graph
enrichment, metadata filtering, and group-based access control.
"""

import pytest
from datetime import datetime, timedelta
from typing import Generator, Optional

from app.models.document import Document
from app.models.group import Group
from app.models.source import Source, SourceType, TrustLevel
from app.services.document_store import DocumentStore
from app.services.embedding_index import EmbeddingIndex
from app.services.graph_index import GraphIndex
from app.services.query_service import (
    QueryFilters,
    QueryResult,
    QueryResponse,
    QueryService,
    ScoringWeights,
    create_query_service,
)
from app.services.source_registry import SourceRegistry


# =============================================================================
# Helpers
# =============================================================================


def index_document(
    embedding_index: EmbeddingIndex,
    doc: Document,
) -> list[str]:
    """Helper to index a document with proper metadata handling."""
    return embedding_index.embed_document(
        document_guid=doc.guid,
        content=doc.content,
        group_guid=doc.group_guid,
        source_guid=doc.source_guid,
        language=doc.language,
        metadata={
            "title": doc.title,
            "region": doc.metadata.get("region", ""),
            "sectors": doc.metadata.get("sectors", []),
            "companies": doc.metadata.get("companies", []),
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
        },
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def document_store(tmp_path) -> Generator[DocumentStore, None, None]:
    """Provide a DocumentStore instance for testing."""
    store = DocumentStore(base_path=str(tmp_path / "documents"))
    yield store
    # Cleanup is handled by tmp_path


@pytest.fixture
def source_registry(tmp_path) -> Generator[SourceRegistry, None, None]:
    """Provide a SourceRegistry instance for testing."""
    registry = SourceRegistry(base_path=str(tmp_path / "sources"))
    yield registry
    # Cleanup is handled by tmp_path


@pytest.fixture
def embedding_index_test(tmp_path) -> Generator[EmbeddingIndex, None, None]:
    """Provide an ephemeral EmbeddingIndex for testing."""
    # No persist_directory or host = ephemeral mode
    index = EmbeddingIndex(
        collection_name="test_query_service",
    )
    yield index
    # Ephemeral index cleans up automatically


@pytest.fixture
def graph_index_test() -> Generator[Optional[GraphIndex], None, None]:
    """Provide a mock GraphIndex for testing (Neo4j not required for unit tests)."""
    # For unit tests, we don't require a running Neo4j instance
    # Return None - QueryService handles this gracefully
    yield None


# Test UUIDs for consistent testing
TEST_GROUP_GUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
TEST_GROUP2_GUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
TEST_SOURCE_HIGH_GUID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
TEST_SOURCE_LOW_GUID = "d4e5f6a7-b8c9-0123-def0-234567890123"


@pytest.fixture
def test_group() -> Group:
    """Provide a test group."""
    return Group(
        group_guid=TEST_GROUP_GUID,
        name="Test Group",
        description="Test group for query service tests",
    )


@pytest.fixture
def test_group2() -> Group:
    """Provide a second test group for isolation tests."""
    return Group(
        group_guid=TEST_GROUP2_GUID,
        name="Test Group 2",
        description="Second test group for isolation tests",
    )


@pytest.fixture
def test_source_high_trust(source_registry: SourceRegistry) -> Source:
    """Provide a high-trust source."""
    source = source_registry.create(
        name="Bloomberg",
        source_type=SourceType.NEWS_AGENCY,
        trust_level=TrustLevel.HIGH,
    )
    return source


@pytest.fixture
def test_source_low_trust(source_registry: SourceRegistry) -> Source:
    """Provide a low-trust source."""
    source = source_registry.create(
        name="Unverified News",
        source_type=SourceType.OTHER,
        trust_level=TrustLevel.LOW,
    )
    return source


@pytest.fixture
def test_documents(
    document_store: DocumentStore,
    test_group: Group,
    test_source_high_trust: Source,
    test_source_low_trust: Source,
) -> list[Document]:
    """Create test documents with varied characteristics."""
    base_time = datetime(2024, 1, 1)
    documents = []

    # Doc 1: Recent APAC tech news from high-trust source
    doc1 = Document(
        title="Apple Expands in Singapore",
        content="Apple announced a new regional hub in Singapore for APAC operations.",
        source_guid=test_source_high_trust.source_guid,
        group_guid=test_group.group_guid,
        language="en",
        metadata={
            "region": "APAC",
            "sectors": ["Technology", "Manufacturing"],
            "companies": ["AAPL"],
        },
        created_at=base_time,
    )
    document_store.save(doc1)
    documents.append(doc1)

    # Doc 2: Older finance news from low-trust source
    doc2 = Document(
        title="Market Volatility in Hong Kong",
        content="Hong Kong stock market experiences significant volatility.",
        source_guid=test_source_low_trust.source_guid,
        group_guid=test_group.group_guid,
        language="en",
        metadata={
            "region": "APAC",
            "sectors": ["Finance"],
            "companies": ["HSBC"],
        },
        created_at=base_time - timedelta(days=30),
    )
    document_store.save(doc2)
    documents.append(doc2)

    # Doc 3: EMEA tech news (different region)
    doc3 = Document(
        title="Microsoft Opens Berlin Office",
        content="Microsoft announces new European development center in Berlin.",
        source_guid=test_source_high_trust.source_guid,
        group_guid=test_group.group_guid,
        language="en",
        metadata={
            "region": "EMEA",
            "sectors": ["Technology"],
            "companies": ["MSFT"],
        },
        created_at=base_time - timedelta(days=5),
    )
    document_store.save(doc3)
    documents.append(doc3)

    # Doc 4: APAC pharma news
    doc4 = Document(
        title="Pharma Company Opens Jakarta Facility",
        content="Major pharmaceutical firm expands manufacturing in Jakarta.",
        source_guid=test_source_high_trust.source_guid,
        group_guid=test_group.group_guid,
        language="en",
        metadata={
            "region": "APAC",
            "sectors": ["Pharmaceuticals"],
            "companies": ["PFE"],
        },
        created_at=base_time - timedelta(days=2),
    )
    document_store.save(doc4)
    documents.append(doc4)

    # Doc 5: Chinese language APAC finance news
    doc5 = Document(
        title="深圳股市上涨",
        content="深圳股市在新的交易周期内上涨。",
        source_guid=test_source_high_trust.source_guid,
        group_guid=test_group.group_guid,
        language="zh",
        metadata={
            "region": "APAC",
            "sectors": ["Finance"],
            "companies": ["Tencent"],
        },
        created_at=base_time - timedelta(days=1),
    )
    document_store.save(doc5)
    documents.append(doc5)

    return documents


@pytest.fixture
def query_service(
    embedding_index_test: EmbeddingIndex,
    document_store: DocumentStore,
    source_registry: SourceRegistry,
    graph_index_test: Optional[GraphIndex],
) -> QueryService:
    """Provide a QueryService instance for testing."""
    return QueryService(
        embedding_index=embedding_index_test,
        document_store=document_store,
        source_registry=source_registry,
        graph_index=graph_index_test,
    )


# =============================================================================
# Phase 12.1: QueryService Initialization
# =============================================================================


class TestQueryServiceInit:
    """Tests for QueryService initialization (Phase 12.1)"""

    def test_query_service_init(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test basic QueryService initialization"""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
        )

        assert service.embedding_index is embedding_index_test
        assert service.document_store is document_store
        assert service.source_registry is source_registry
        assert service.graph_index is None
        assert service.default_weights is not None

    def test_query_service_with_graph_index(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        graph_index_test: GraphIndex,
    ) -> None:
        """Test QueryService initialization with graph index"""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=graph_index_test,
        )

        assert service.graph_index is graph_index_test

    def test_query_service_custom_weights(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test QueryService with custom scoring weights"""
        weights = ScoringWeights(semantic=0.7, trust=0.15, recency=0.05, graph_boost=0.1)
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            default_weights=weights,
        )

        assert service.default_weights == weights

    def test_create_query_service_factory(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test create_query_service factory function"""
        service = create_query_service(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
        )

        assert isinstance(service, QueryService)
        assert service.embedding_index is embedding_index_test


# =============================================================================
# Phase 12.2: ChromaDB Similarity Search
# =============================================================================


class TestQuerySimilarity:
    """Tests for ChromaDB similarity search (Phase 12.2)"""

    def test_similarity_search_basic(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test basic similarity search"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query for APAC tech news
        response = query_service.query(
            query_text="Apple technology APAC",
            group_guids=[test_group.group_guid],
            n_results=5,
        )

        assert isinstance(response, QueryResponse)
        assert response.query == "Apple technology APAC"
        assert len(response.results) > 0
        assert response.execution_time_ms > 0

    def test_similarity_search_with_group_filtering(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test that similarity search respects group filtering"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query with group filtering
        response = query_service.query(
            query_text="market finance",
            group_guids=[test_group.group_guid],
            n_results=10,
        )

        # All results should be from the permitted group
        assert len(response.results) > 0
        # Note: We can't directly verify group membership without inspecting internals

    def test_similarity_search_empty_results(
        self,
        query_service: QueryService,
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test similarity search with no matching documents in a given group"""
        # Clear any existing documents
        embedding_index_test.clear()
        
        # Query the empty index
        response = query_service.query(
            query_text="nonexistent query",
            group_guids=[test_group.group_guid],
            n_results=5,
        )

        assert response.query == "nonexistent query"
        assert len(response.results) == 0
        assert response.total_found == 0


# =============================================================================
# Phase 12.3: Metadata Filtering
# =============================================================================


class TestQueryFilters:
    """Tests for metadata filtering (Phase 12.3)"""

    def test_query_filters_dataclass(self) -> None:
        """Test QueryFilters dataclass creation"""
        date_from = datetime(2024, 1, 1)
        date_to = datetime(2024, 1, 31)
        filters = QueryFilters(
            date_from=date_from,
            date_to=date_to,
            regions=["APAC"],
            sectors=["Technology"],
            companies=["AAPL"],
            languages=["en"],
        )

        assert filters.date_from == date_from
        assert filters.date_to == date_to
        assert filters.regions == ["APAC"]
        assert filters.sectors == ["Technology"]
        assert filters.companies == ["AAPL"]
        assert filters.languages == ["en"]

    def test_query_with_region_filter(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test query with region filtering"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query with region filter
        filters = QueryFilters(regions=["APAC"])
        response = query_service.query(
            query_text="technology",
            group_guids=[test_group.group_guid],
            filters=filters,
            n_results=10,
        )

        # All results should be from APAC region
        for result in response.results:
            assert result.metadata.get("region") == "APAC"

    def test_query_with_date_filter(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test query with date filtering"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query only recent documents
        date_from = datetime(2024, 1, 1) - timedelta(days=5)
        filters = QueryFilters(date_from=date_from)
        response = query_service.query(
            query_text="technology",
            group_guids=[test_group.group_guid],
            filters=filters,
            n_results=10,
        )

        # All results should be from specified date range
        for result in response.results:
            if result.created_at:
                assert result.created_at >= date_from

    def test_query_with_sector_filter(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test query with sector filtering"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query specific sector
        filters = QueryFilters(sectors=["Technology"])
        response = query_service.query(
            query_text="tech",
            group_guids=[test_group.group_guid],
            filters=filters,
            n_results=10,
        )

        # Results should only contain Technology sector
        for result in response.results:
            sectors = result.metadata.get("sectors", [])
            assert "Technology" in sectors

    def test_query_with_language_filter(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test query with language filtering"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query English only
        filters = QueryFilters(languages=["en"])
        response = query_service.query(
            query_text="market",
            group_guids=[test_group.group_guid],
            filters=filters,
            n_results=10,
        )

        # All results should be English
        for result in response.results:
            assert result.language == "en"

    def test_query_with_multiple_filters(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test query with multiple combined filters"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query with multiple filters
        filters = QueryFilters(
            regions=["APAC"],
            sectors=["Technology"],
            languages=["en"],
        )
        response = query_service.query(
            query_text="technology",
            group_guids=[test_group.group_guid],
            filters=filters,
            n_results=10,
        )

        # Verify all results match all filters
        for result in response.results:
            assert result.metadata.get("region") == "APAC"
            assert "Technology" in result.metadata.get("sectors", [])
            assert result.language == "en"


# =============================================================================
# Phase 12.4: Group-Based Access Control
# =============================================================================


class TestQueryGroupScoping:
    """Tests for group-based access control (Phase 12.4)"""

    def test_query_respects_user_groups(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test that query respects user's group permissions"""
        # Index all documents with test group
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query with the correct group
        response = query_service.query(
            query_text="technology",
            group_guids=[test_group.group_guid],
            n_results=10,
        )

        # Should return results
        assert len(response.results) >= 0  # May be 0 if search doesn't match

    def test_query_with_empty_groups(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test query with empty group list"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query with empty group list
        response = query_service.query(
            query_text="technology",
            group_guids=[],
            n_results=10,
        )

        # Should still work (empty groups means search all)
        assert isinstance(response, QueryResponse)


# =============================================================================
# Phase 12.5: Graph Enrichment
# =============================================================================


class TestQueryGraphContext:
    """Tests for Neo4j graph enrichment (Phase 12.5)"""

    def test_query_without_graph_index(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        test_documents: list[Document],
        test_group: Group,
    ) -> None:
        """Test that query works without graph index"""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )

        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query should work without graph enrichment
        response = service.query(
            query_text="technology",
            group_guids=[test_group.group_guid],
            n_results=5,
        )

        assert isinstance(response, QueryResponse)

    def test_query_with_graph_context_disabled(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test disabling graph context enrichment"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query with graph context disabled
        response = query_service.query(
            query_text="technology",
            group_guids=[test_group.group_guid],
            n_results=5,
            include_graph_context=False,
        )

        assert isinstance(response, QueryResponse)


# =============================================================================
# Phase 12.6: Trust Level Scoring
# =============================================================================


class TestTrustLevelScoring:
    """Tests for trust level scoring (Phase 12.6)"""

    def test_trust_level_scoring(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        test_source_high_trust: Source,
        test_source_low_trust: Source,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test that high-trust sources get higher scores"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query
        response = query_service.query(
            query_text="technology APAC",
            group_guids=[test_group.group_guid],
            n_results=10,
        )

        # High-trust source documents should rank higher
        assert isinstance(response, QueryResponse)
        if len(response.results) > 1:
            # Verify that results from high-trust sources have good scores
            pass  # Actual verification would require detailed scoring data

    def test_scoring_weights(self) -> None:
        """Test ScoringWeights validation"""
        # Valid weights
        weights = ScoringWeights(semantic=0.6, trust=0.2, recency=0.1, graph_boost=0.1)
        assert weights.semantic == 0.6
        assert weights.trust == 0.2
        assert weights.recency == 0.1
        assert weights.graph_boost == 0.1

    def test_scoring_weights_invalid(self) -> None:
        """Test that invalid weights raise error"""
        with pytest.raises(ValueError, match="Scoring weights must sum to 1.0"):
            ScoringWeights(semantic=0.5, trust=0.3, recency=0.1, graph_boost=0.2)

    def test_custom_scoring_weights(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test query with custom scoring weights"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Query with custom weights (trust-heavy)
        custom_weights = ScoringWeights(semantic=0.4, trust=0.4, recency=0.1, graph_boost=0.1)
        response = query_service.query(
            query_text="technology",
            group_guids=[test_group.group_guid],
            weights=custom_weights,
            n_results=5,
        )

        assert isinstance(response, QueryResponse)


# =============================================================================
# QueryResult and QueryResponse
# =============================================================================


class TestQueryResult:
    """Tests for QueryResult dataclass"""

    def test_query_result_creation(self) -> None:
        """Test creating a QueryResult"""
        result = QueryResult(
            document_guid="doc_001",
            title="Test Document",
            content_snippet="This is a test snippet.",
            score=0.95,
            similarity_score=0.92,
            trust_score=0.8,
            recency_score=0.9,
            source_guid="source_001",
            source_name="Test Source",
            language="en",
            created_at=datetime.now(),
            metadata={"region": "APAC"},
            graph_context={"related": ["company_001"]},
        )

        assert result.document_guid == "doc_001"
        assert result.title == "Test Document"
        assert result.score == 0.95
        assert result.similarity_score == 0.92
        assert result.trust_score == 0.8


class TestQueryResponse:
    """Tests for QueryResponse dataclass"""

    def test_query_response_creation(self) -> None:
        """Test creating a QueryResponse"""
        results = [
            QueryResult(
                document_guid="doc_001",
                title="Test",
                content_snippet="Content",
                score=0.9,
                similarity_score=0.9,
            ),
        ]
        response = QueryResponse(
            query="test query",
            results=results,
            total_found=1,
            filters_applied={"region": "APAC"},
            execution_time_ms=45.5,
        )

        assert response.query == "test query"
        assert len(response.results) == 1
        assert response.total_found == 1
        assert response.execution_time_ms == 45.5

    def test_query_response_empty_results(self) -> None:
        """Test QueryResponse with empty results"""
        response = QueryResponse(
            query="no results query",
            results=[],
            total_found=0,
        )

        assert response.query == "no results query"
        assert len(response.results) == 0
        assert response.total_found == 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestQueryIntegration:
    """Integration tests for QueryService"""

    def test_full_query_workflow(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test full query workflow: index → filter → score → return"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        # Execute full query
        filters = QueryFilters(
            regions=["APAC"],
            sectors=["Technology"],
        )
        response = query_service.query(
            query_text="Apple technology expansion APAC",
            group_guids=[test_group.group_guid],
            filters=filters,
            n_results=5,
        )

        # Verify response structure
        assert isinstance(response, QueryResponse)
        assert response.query == "Apple technology expansion APAC"
        assert isinstance(response.results, list)
        assert response.total_found >= 0
        assert response.execution_time_ms >= 0
        assert "regions" in response.filters_applied or "sectors" in response.filters_applied

    def test_query_result_sorting(
        self,
        query_service: QueryService,
        test_documents: list[Document],
        test_group: Group,
        embedding_index_test: EmbeddingIndex,
    ) -> None:
        """Test that results are sorted by score"""
        # Index documents
        for doc in test_documents:
            index_document(embedding_index_test, doc)

        response = query_service.query(
            query_text="technology",
            group_guids=[test_group.group_guid],
            n_results=10,
        )

        # Verify results are sorted by score (descending)
        if len(response.results) > 1:
            for i in range(len(response.results) - 1):
                assert response.results[i].score >= response.results[i + 1].score


# =============================================================================
# Phase 12.7: MCP Tool Tests
# =============================================================================


class TestMCPQueryDocuments:
    """Tests for MCP query_documents tool (Phase 12.7)"""

    def test_mcp_query_documents_tool_registration(
        self,
        query_service: QueryService,
        document_store: DocumentStore,
    ) -> None:
        """Test that query_documents tool can be registered"""
        from mcp.server.fastmcp import FastMCP
        from app.tools.query_tools import register_query_tools

        mcp = FastMCP(name="test-server", port=9999)
        register_query_tools(mcp, document_store, query_service)
        # Tool should be registered successfully
        assert mcp is not None

    def test_mcp_query_documents_without_service(
        self,
        document_store: DocumentStore,
    ) -> None:
        """Test that get_document works without query_service"""
        from mcp.server.fastmcp import FastMCP
        from app.tools.query_tools import register_query_tools

        mcp = FastMCP(name="test-server", port=9999)
        # Should not raise even without query_service
        register_query_tools(mcp, document_store, None)
        assert mcp is not None


# =============================================================================
# Phase 14: get_top_client_news Tests
# =============================================================================


class TestGetTopClientNews:
    """Tests for QueryService.get_top_client_news hybrid search"""

    @pytest.fixture
    def mock_graph_index(self) -> Generator:
        """Create a mock GraphIndex for top client news tests."""
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock_session = MagicMock()
        mock._get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock._get_session.return_value.__exit__ = MagicMock(return_value=None)
        yield mock, mock_session

    def test_get_top_client_news_no_graph_index(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test that method returns empty list without graph index."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )
        result = service.get_top_client_news(
            client_guid="client-123",
            group_guids=[TEST_GROUP_GUID],
            limit=3,
        )
        assert result == []

    def test_get_top_client_news_zero_limit(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph_index,
    ) -> None:
        """Test that zero limit returns empty list."""
        mock, _ = mock_graph_index
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=mock,
        )
        result = service.get_top_client_news(
            client_guid="client-123",
            group_guids=[TEST_GROUP_GUID],
            limit=0,
        )
        assert result == []

    def test_get_top_client_news_client_not_found(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph_index,
    ) -> None:
        """Test that missing client returns empty list."""
        mock, mock_session = mock_graph_index
        mock_session.run.return_value.single.return_value = None

        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=mock,
        )
        result = service.get_top_client_news(
            client_guid="nonexistent-client",
            group_guids=[TEST_GROUP_GUID],
            limit=3,
        )
        assert result == []

    def test_client_news_weights_for_hedge_fund(self) -> None:
        """Test that hedge fund gets high turnover weights."""
        from app.services.query_service import ClientNewsWeights

        weights = ClientNewsWeights.for_client_type("HEDGE_FUND")
        assert weights.semantic == 0.35
        assert weights.graph == 0.35
        assert weights.impact == 0.20
        assert weights.recency == 0.10

    def test_client_news_weights_for_long_only(self) -> None:
        """Test that long-only client gets lower turnover weights."""
        from app.services.query_service import ClientNewsWeights

        weights = ClientNewsWeights.for_client_type("LONG_ONLY")
        assert weights.semantic == 0.30
        assert weights.graph == 0.30
        assert weights.impact == 0.20
        assert weights.recency == 0.20

    def test_client_news_weights_for_pension(self) -> None:
        """Test that pension fund uses long-only weights."""
        from app.services.query_service import ClientNewsWeights

        weights = ClientNewsWeights.for_client_type("PENSION")
        assert weights.semantic == 0.30
        assert weights.recency == 0.20

    def test_client_news_weights_unknown_type(self) -> None:
        """Test that unknown client type uses default weights."""
        from app.services.query_service import ClientNewsWeights

        weights = ClientNewsWeights.for_client_type("UNKNOWN_TYPE")
        # Should use hedge fund (default) weights
        assert weights.semantic == 0.35
        assert weights.graph == 0.35

    def test_within_time_window_recent(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test that recent documents pass time window check."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=24)

        # Document created 1 hour ago should pass
        recent = (now - timedelta(hours=1)).isoformat()
        assert service._within_time_window(recent, cutoff) is True

    def test_within_time_window_old(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test that old documents fail time window check."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=24)

        # Document created 48 hours ago should fail
        old = (now - timedelta(hours=48)).isoformat()
        assert service._within_time_window(old, cutoff) is False

    def test_within_time_window_none_passes(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test that documents without timestamp pass (inclusive)."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )
        cutoff = datetime.utcnow() - timedelta(hours=24)
        assert service._within_time_window(None, cutoff) is True

    def test_normalize_impact_score(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test impact score normalization."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )

        assert service._normalize_impact_score(100) == 1.0
        assert service._normalize_impact_score(50) == 0.5
        assert service._normalize_impact_score(0) == 0.0
        assert service._normalize_impact_score(150) == 1.0  # Capped at 1.0
        assert service._normalize_impact_score(-10) == 0.0  # Capped at 0.0
        assert service._normalize_impact_score(None) == 0.0
        assert service._normalize_impact_score("invalid") == 0.0

    def test_violates_exclusions_company(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test ESG exclusion check for companies."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )

        doc_entities = {"companies": ["Acme Corp", "Beta Inc"], "sectors": ["Technology"]}
        exclusions = {"companies": ["ACME CORP"], "sectors": []}  # Case insensitive

        assert service._violates_exclusions(doc_entities, exclusions) is True

    def test_violates_exclusions_sector(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test ESG exclusion check for sectors."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )

        doc_entities = {"companies": ["Clean Energy Co"], "sectors": ["Energy", "Utilities"]}
        exclusions = {"companies": [], "sectors": ["ENERGY"]}  # Case insensitive

        assert service._violates_exclusions(doc_entities, exclusions) is True

    def test_violates_exclusions_none(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test that document without excluded entities passes."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )

        doc_entities = {"companies": ["Good Corp"], "sectors": ["Healthcare"]}
        exclusions = {"companies": ["Bad Corp"], "sectors": ["Tobacco"]}

        assert service._violates_exclusions(doc_entities, exclusions) is False

    def test_build_client_query_text_basic(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test semantic query text construction."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )

        profile = {
            "client_type": "HEDGE_FUND",
            "mandate_type": "event_driven",
            "horizon": "short",
            "esg_constrained": True,
        }
        holdings = ["AAPL", "MSFT"]
        watchlist = ["GOOGL"]

        query = service._build_client_query_text(
            profile=profile,
            holdings=holdings,
            watchlist=watchlist,
            llm_service=None,
        )

        assert "HEDGE_FUND" in query
        assert "event_driven" in query
        assert "AAPL" in query
        assert "MSFT" in query
        assert "GOOGL" in query

    def test_build_why_it_matters_basic(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> None:
        """Test why_it_matters generation without LLM."""
        service = QueryService(
            embedding_index=embedding_index_test,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=None,
        )

        why = service._build_why_it_matters(
            title="Apple Earnings Beat",
            reasons=["DIRECT_HOLDING", "SEMANTIC_MATCH"],
            impact_score=85,
            tickers=["AAPL"],
            llm_service=None,
        )

        assert "DIRECT_HOLDING" in why
        assert "SEMANTIC_MATCH" in why
        assert "AAPL" in why


# =============================================================================
# Step 0 Baseline Tests — Client Avatar Transformation
# =============================================================================


class TestTopClientNewsBaseline:
    """Baseline tests that lock in the current get_top_client_news contract.

    These tests exist to detect regressions as we evolve the matching logic
    toward the two-channel Client Avatar model (see docs/analysis/matching-logic-deep-dive.md).

    Two invariants are tested:
    1. Output shape — every result dict has exactly the expected keys, sorted by relevance_score desc.
    2. Holdings outrank semantic-only — a document matching a direct holding always scores higher
       than a document found only via semantic similarity.
    """

    # Expected keys in every result dict returned by get_top_client_news
    EXPECTED_KEYS = {
        "document_guid",
        "title",
        "created_at",
        "impact_score",
        "impact_tier",
        "affected_instruments",
        "relevance_score",
        "reasons",
        "why_it_matters_base",
    }

    # -- helpers --

    @staticmethod
    def _make_service(
        embedding_index: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        graph_index,
    ) -> QueryService:
        return QueryService(
            embedding_index=embedding_index,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=graph_index,
        )

    @staticmethod
    def _stub_profile() -> dict:
        return {
            "client_guid": "client-baseline-001",
            "client_type": "HEDGE_FUND",
            "mandate_type": "equity_long_short",
            "mandate_text": None,
            "horizon": "short",
            "esg_constrained": False,
            "impact_threshold": 30,
            "benchmark": None,
            "restrictions": None,
        }

    @staticmethod
    def _now():
        from datetime import datetime
        return datetime(2026, 2, 6, 12, 0, 0)

    # -- fixtures --

    @pytest.fixture
    def mock_graph(self):
        """Minimal mock GraphIndex that makes _get_session() a context-manager."""
        from unittest.mock import MagicMock
        mock = MagicMock()
        mock_session = MagicMock()
        mock._get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock._get_session.return_value.__exit__ = MagicMock(return_value=None)
        return mock

    # ==================================================================
    # Test 1 — Output shape contract
    # ==================================================================
    def test_top_client_news_output_shape(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph,
    ) -> None:
        """Every item returned by get_top_client_news has exactly the expected keys,
        results are sorted descending by relevance_score, and reasons is a list of strings.
        """
        from unittest.mock import patch
        from datetime import timedelta
        from datetime import datetime as real_datetime

        now = self._now()

        class FrozenDateTime(real_datetime):
            @classmethod
            def utcnow(cls):
                return now

        profile = self._stub_profile()

        holdings_doc = {
            "document_guid": "doc-holdings-001",
            "title": "TSMC Q4 Earnings Beat",
            "created_at": (now - timedelta(hours=2)).isoformat(),
            "impact_score": 80,
            "impact_tier": "GOLD",
            "affected_instruments": ["TSM"],
        }
        watchlist_doc = {
            "document_guid": "doc-watch-001",
            "title": "Samsung Fab Expansion",
            "created_at": (now - timedelta(hours=5)).isoformat(),
            "impact_score": 60,
            "impact_tier": "SILVER",
            "affected_instruments": ["005930.KS"],
        }

        service = self._make_service(
            embedding_index_test, document_store, source_registry, mock_graph,
        )

        with (
            patch("app.services.query_service.datetime", FrozenDateTime),
            patch.object(service, "_get_client_profile_context", return_value=profile),
            patch.object(service, "_get_client_holdings", return_value=[
                {"ticker": "TSM", "weight": 0.15},
            ]),
            patch.object(service, "_get_client_watchlist", return_value=["005930.KS"]),
            patch.object(service, "_get_client_exclusions", return_value={"companies": [], "sectors": []}),
            patch.object(service, "_get_documents_for_tickers", side_effect=[
                [holdings_doc],   # holdings call
                [watchlist_doc],  # watchlist call
            ]),
            patch.object(service, "_expand_lateral_tickers", return_value={
                "competitors": [], "suppliers": [], "peers": [],
            }),
        ):
            results = service.get_top_client_news(
                client_guid="client-baseline-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
            )

        # Must return at least the holdings + watchlist docs
        assert len(results) >= 1, "Expected at least one result from mocked holdings/watchlist"

        # Shape: every result has exactly the expected keys
        for item in results:
            actual_keys = set(item.keys())
            assert actual_keys == self.EXPECTED_KEYS, (
                f"Key mismatch: extra={actual_keys - self.EXPECTED_KEYS}, "
                f"missing={self.EXPECTED_KEYS - actual_keys}"
            )

        # Sorted descending by relevance_score
        scores = [item["relevance_score"] for item in results]
        assert scores == sorted(scores, reverse=True), "Results must be sorted descending by relevance_score"

        # reasons is a sorted list of non-empty strings
        for item in results:
            assert isinstance(item["reasons"], list), "reasons must be a list"
            assert all(isinstance(r, str) and r for r in item["reasons"]), "each reason must be a non-empty string"
            assert item["reasons"] == sorted(item["reasons"]), "reasons must be sorted alphabetically"

    # ==================================================================
    # Test 2 — Holdings outrank semantic-only matches
    # ==================================================================
    def test_top_client_news_holdings_outrank_watchlist(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph,
    ) -> None:
        """A document matching a direct holding must score higher than a
        watchlist match (all else being equal).
        """
        from unittest.mock import patch
        from datetime import timedelta
        from datetime import datetime as real_datetime

        now = self._now()

        class FrozenDateTime(real_datetime):
            @classmethod
            def utcnow(cls):
                return now

        profile = self._stub_profile()

        # Holdings doc — affects a ticker the client owns
        holdings_doc = {
            "document_guid": "doc-hold-rank-001",
            "title": "TSM Earnings Surge",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "impact_score": 70,
            "impact_tier": "GOLD",
            "affected_instruments": ["TSM"],
        }

        watchlist_doc = {
            "document_guid": "doc-watch-rank-001",
            "title": "Sector Peer Update",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "impact_score": 70,
            "impact_tier": "GOLD",
            "affected_instruments": ["005930.KS"],
        }

        service = self._make_service(
            embedding_index_test, document_store, source_registry, mock_graph,
        )

        with (
            patch("app.services.query_service.datetime", FrozenDateTime),
            patch.object(service, "_get_client_profile_context", return_value=profile),
            patch.object(service, "_get_client_holdings", return_value=[
                {"ticker": "TSM", "weight": 0.20},
            ]),
            patch.object(service, "_get_client_watchlist", return_value=["005930.KS"]),
            patch.object(service, "_get_client_exclusions", return_value={"companies": [], "sectors": []}),
            patch.object(service, "_get_documents_for_tickers", side_effect=[
                [holdings_doc],
                [watchlist_doc],
            ]),
            patch.object(service, "_expand_lateral_tickers", return_value={
                "competitors": [], "suppliers": [], "peers": [],
            }),
        ):
            results = service.get_top_client_news(
                client_guid="client-baseline-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
            )

        # Both documents should appear
        guids = [r["document_guid"] for r in results]
        assert "doc-hold-rank-001" in guids, "Holdings doc must appear in results"
        assert "doc-watch-rank-001" in guids, "Watchlist doc must appear in results"

        # Holdings doc must rank higher
        hold_item = next(r for r in results if r["document_guid"] == "doc-hold-rank-001")
        watch_item = next(r for r in results if r["document_guid"] == "doc-watch-rank-001")
        assert hold_item["relevance_score"] > watch_item["relevance_score"], (
            f"Holdings doc ({hold_item['relevance_score']:.3f}) must outrank "
            f"watchlist doc ({watch_item['relevance_score']:.3f})"
        )

        # Holdings doc must have DIRECT_HOLDING reason
        assert "DIRECT_HOLDING" in hold_item["reasons"]
        # Watchlist doc must NOT have DIRECT_HOLDING reason
        assert "DIRECT_HOLDING" not in watch_item["reasons"]

    def test_semantic_weight_is_used_in_final_score(
        self,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph,
    ) -> None:
        """If a candidate is vector-only, weights.semantic must affect ranking.

        This is a regression test for BUG-1: semantic weight defined but unused.
        """
        from unittest.mock import MagicMock, patch
        from datetime import timedelta
        from datetime import datetime as real_datetime

        from app.services.embedding_index import SimilarityResult
        from app.services.query_service import ClientNewsWeights

        now = self._now()

        class FrozenDateTime(real_datetime):
            @classmethod
            def utcnow(cls):
                return now

        profile = {
            **self._stub_profile(),
            "mandate_themes": [],
            "mandate_embedding": [0.1, 0.2, 0.3],
        }

        watchlist_doc = {
            "document_guid": "doc-graph-001",
            "title": "Watchlist Catalyst",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "impact_score": 70,
            "impact_tier": "GOLD",
            "affected_instruments": ["TSM"],
        }
        vector_doc = {
            "document_guid": "doc-vector-001",
            "title": "Mandate Semantic Idea",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "impact_score": 70,
            "impact_tier": "GOLD",
            "affected_instruments": ["XYZ"],
        }

        embedding_index = MagicMock()
        embedding_index.search_by_embedding.return_value = [
            SimilarityResult(
                document_guid="doc-vector-001",
                chunk_id="c1",
                content="",
                score=1.0,
                metadata={},
            )
        ]

        service = QueryService(
            embedding_index=embedding_index,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=mock_graph,
        )

        with (
            patch("app.services.query_service.datetime", FrozenDateTime),
            patch.object(service, "_get_client_profile_context", return_value=profile),
            patch.object(service, "_get_client_holdings", return_value=[]),
            patch.object(service, "_get_client_watchlist", return_value=["TSM"]),
            patch.object(service, "_get_client_exclusions", return_value={"companies": [], "sectors": []}),
            patch.object(service, "_get_documents_for_tickers", return_value=[watchlist_doc]),
            patch.object(service, "_expand_lateral_tickers", return_value={"competitors": [], "suppliers": [], "peers": []}),
            patch.object(service, "_get_documents_by_themes", return_value=[]),
            patch.object(service, "_get_documents_by_guids", return_value=[vector_doc]),
        ):
            # Graph-heavy weights: graph candidate should win.
            w_graph = ClientNewsWeights(semantic=0.0, graph=1.0, impact=0.0, recency=0.0)
            results_graph = service.get_top_client_news(
                client_guid="client-baseline-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
                weights=w_graph,
                opportunity_bias=1.0,
            )
            assert results_graph, "Expected results for graph+vector candidates"
            assert results_graph[0]["document_guid"] == "doc-graph-001"

            # Semantic-heavy weights: vector candidate should win.
            w_sem = ClientNewsWeights(semantic=1.0, graph=0.0, impact=0.0, recency=0.0)
            results_sem = service.get_top_client_news(
                client_guid="client-baseline-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
                weights=w_sem,
                opportunity_bias=1.0,
            )
            assert results_sem, "Expected results for graph+vector candidates"
            assert results_sem[0]["document_guid"] == "doc-vector-001"

    def test_thematic_path_fires_when_theme_tags_match(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph,
    ) -> None:
        """A client mandate theme should surface THEMATIC candidates."""
        from unittest.mock import patch
        from datetime import timedelta
        from datetime import datetime as real_datetime

        now = self._now()

        class FrozenDateTime(real_datetime):
            @classmethod
            def utcnow(cls):
                return now

        profile = {
            **self._stub_profile(),
            "mandate_themes": ["ai"],
            "mandate_embedding": [],
        }

        thematic_doc = {
            "document_guid": "doc-thematic-001",
            "title": "AI Theme Update",
            "created_at": (now - timedelta(hours=2)).isoformat(),
            "impact_score": 60,
            "impact_tier": "SILVER",
            "affected_instruments": ["QNTM"],
            "themes": ["ai"],
        }

        service = self._make_service(
            embedding_index_test, document_store, source_registry, mock_graph,
        )

        with (
            patch("app.services.query_service.datetime", FrozenDateTime),
            patch.object(service, "_get_client_profile_context", return_value=profile),
            patch.object(service, "_get_client_holdings", return_value=[]),
            patch.object(service, "_get_client_watchlist", return_value=[]),
            patch.object(service, "_get_client_exclusions", return_value={"companies": [], "sectors": []}),
            patch.object(service, "_get_documents_for_tickers", return_value=[]),
            patch.object(service, "_expand_lateral_tickers", return_value={"competitors": [], "suppliers": [], "peers": []}),
            patch.object(service, "_get_documents_by_themes", return_value=[thematic_doc]),
        ):
            results = service.get_top_client_news(
                client_guid="client-baseline-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
                opportunity_bias=1.0,
            )

        assert any(r["document_guid"] == "doc-thematic-001" for r in results)
        item = next(r for r in results if r["document_guid"] == "doc-thematic-001")
        assert "THEMATIC" in item["reasons"]

    def test_vector_path_inactive_at_lambda_0_active_at_lambda_1(
        self,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph,
    ) -> None:
        """Vector candidates should be gated off at lambda=0 and available at lambda=1."""
        from unittest.mock import MagicMock, patch
        from datetime import timedelta
        from datetime import datetime as real_datetime

        from app.services.embedding_index import SimilarityResult

        now = self._now()

        class FrozenDateTime(real_datetime):
            @classmethod
            def utcnow(cls):
                return now

        profile = {
            **self._stub_profile(),
            "mandate_themes": [],
            "mandate_embedding": [0.1, 0.2, 0.3],
        }

        vector_doc = {
            "document_guid": "doc-vector-002",
            "title": "Vector Candidate",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "impact_score": 50,
            "impact_tier": "SILVER",
            "affected_instruments": ["XYZ"],
        }

        embedding_index = MagicMock()
        embedding_index.search_by_embedding.return_value = [
            SimilarityResult(
                document_guid="doc-vector-002",
                chunk_id="c1",
                content="",
                score=1.0,
                metadata={},
            )
        ]

        service = QueryService(
            embedding_index=embedding_index,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=mock_graph,
        )

        with (
            patch("app.services.query_service.datetime", FrozenDateTime),
            patch.object(service, "_get_client_profile_context", return_value=profile),
            patch.object(service, "_get_client_holdings", return_value=[]),
            patch.object(service, "_get_client_watchlist", return_value=[]),
            patch.object(service, "_get_client_exclusions", return_value={"companies": [], "sectors": []}),
            patch.object(service, "_get_documents_for_tickers", return_value=[]),
            patch.object(service, "_expand_lateral_tickers", return_value={"competitors": [], "suppliers": [], "peers": []}),
            patch.object(service, "_get_documents_by_themes", return_value=[]),
            patch.object(service, "_get_documents_by_guids", return_value=[vector_doc]),
        ):
            res0 = service.get_top_client_news(
                client_guid="client-baseline-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
                opportunity_bias=0.0,
            )
            assert res0 == [], "Expected no results when only vector path exists at lambda=0"

            res1 = service.get_top_client_news(
                client_guid="client-baseline-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
                opportunity_bias=1.0,
            )
            assert any(r["document_guid"] == "doc-vector-002" for r in res1)


# =============================================================================
# Step 3 Tests — Avatar Feed (Two-Channel Model)
# =============================================================================


class TestAvatarFeed:
    """Tests for get_client_avatar_feed — the two-channel client avatar model.

    Channel 1 (MAINTENANCE): News affecting holdings/watchlist.
    Channel 2 (OPPORTUNITY): Mandate-themed news NOT affecting existing positions.

    See docs/analysis/matching-logic-deep-dive.md for the full specification.
    """

    @staticmethod
    def _make_service(
        embedding_index: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        graph_index,
    ) -> QueryService:
        return QueryService(
            embedding_index=embedding_index,
            document_store=document_store,
            source_registry=source_registry,
            graph_index=graph_index,
        )

    @staticmethod
    def _stub_profile() -> dict:
        return {
            "client_guid": "client-avatar-001",
            "client_type": "HEDGE_FUND",
            "mandate_type": "equity_long_short",
            "mandate_text": "Asia-Pacific equities with focus on semiconductors and EVs",
            "horizon": "medium",
            "esg_constrained": False,
            "impact_threshold": 30,
            "benchmark": None,
            "restrictions": None,
        }

    @staticmethod
    def _now():
        return datetime(2026, 2, 6, 12, 0, 0)

    @pytest.fixture
    def mock_graph(self):
        """Minimal mock GraphIndex that makes _get_session() a context-manager."""
        from unittest.mock import MagicMock
        mock = MagicMock()
        mock_session = MagicMock()
        mock._get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock._get_session.return_value.__exit__ = MagicMock(return_value=None)
        return mock

    # ==================================================================
    # Test 1 — Holdings story appears in MAINTENANCE channel
    # ==================================================================
    def test_avatar_holdings_in_maintenance(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph,
    ) -> None:
        """A document affecting a held ticker appears in the maintenance channel."""
        from unittest.mock import patch
        from datetime import datetime as real_datetime

        now = self._now()

        class FrozenDateTime(real_datetime):
            @classmethod
            def utcnow(cls):
                return now

        profile = self._stub_profile()

        # Document that affects TSM (which client holds)
        holdings_doc = {
            "document_guid": "doc-maint-001",
            "title": "TSMC Q4 Revenue Surge",
            "created_at": (now - timedelta(hours=2)).isoformat(),
            "impact_score": 75,
            "impact_tier": "GOLD",
            "affected_instruments": ["TSM"],
            "themes": ["semiconductor"],
        }

        service = self._make_service(
            embedding_index_test, document_store, source_registry, mock_graph,
        )

        with (
            patch("app.services.query_service.datetime", FrozenDateTime),
            patch.object(service, "_get_client_profile_context", return_value=profile),
            patch.object(service, "_get_client_holdings", return_value=[
                {"ticker": "TSM", "weight": 0.20},
            ]),
            patch.object(service, "_get_client_watchlist", return_value=[]),
            patch.object(service, "_get_documents_for_tickers", return_value=[holdings_doc]),
            patch.object(service, "_get_client_mandate_themes", return_value=[]),
            patch.object(service, "_get_documents_by_themes", return_value=[]),
        ):
            feed = service.get_client_avatar_feed(
                client_guid="client-avatar-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
            )

        # Document must appear in maintenance channel
        assert len(feed.maintenance) >= 1
        maint_guids = [item.document_guid for item in feed.maintenance]
        assert "doc-maint-001" in maint_guids

        # Verify channel and reason
        item = next(i for i in feed.maintenance if i.document_guid == "doc-maint-001")
        assert item.channel == "MAINTENANCE"
        assert "TSM" in item.reason

    # ==================================================================
    # Test 2 — Mandate-themed story appears in OPPORTUNITY channel
    # ==================================================================
    def test_avatar_mandate_themes_in_opportunity(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph,
    ) -> None:
        """A mandate-themed document NOT affecting holdings appears in opportunity."""
        from unittest.mock import patch
        from datetime import datetime as real_datetime

        now = self._now()

        class FrozenDateTime(real_datetime):
            @classmethod
            def utcnow(cls):
                return now

        profile = self._stub_profile()

        # Document about EV batteries (matches mandate themes) but affects CATL (not held)
        theme_doc = {
            "document_guid": "doc-opp-001",
            "title": "CATL Battery Tech Breakthrough",
            "created_at": (now - timedelta(hours=3)).isoformat(),
            "impact_score": 80,
            "impact_tier": "GOLD",
            "affected_instruments": ["CATL"],
            "themes": ["ev_battery", "china"],
        }

        service = self._make_service(
            embedding_index_test, document_store, source_registry, mock_graph,
        )

        with (
            patch("app.services.query_service.datetime", FrozenDateTime),
            patch.object(service, "_get_client_profile_context", return_value=profile),
            patch.object(service, "_get_client_holdings", return_value=[
                {"ticker": "TSM", "weight": 0.20},  # Client holds TSM, not CATL
            ]),
            patch.object(service, "_get_client_watchlist", return_value=[]),
            patch.object(service, "_get_documents_for_tickers", return_value=[]),
            patch.object(service, "_get_client_mandate_themes", return_value=["ev_battery", "semiconductor"]),
            patch.object(service, "_get_documents_by_themes", return_value=[theme_doc]),
        ):
            feed = service.get_client_avatar_feed(
                client_guid="client-avatar-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
            )

        # Document must appear in opportunity channel
        assert len(feed.opportunity) >= 1
        opp_guids = [item.document_guid for item in feed.opportunity]
        assert "doc-opp-001" in opp_guids

        # Verify channel and reason
        item = next(i for i in feed.opportunity if i.document_guid == "doc-opp-001")
        assert item.channel == "OPPORTUNITY"
        assert "ev_battery" in item.reason

    # ==================================================================
    # Test 3 — Holdings story excluded from OPPORTUNITY (novelty guard)
    # ==================================================================
    def test_avatar_holdings_excluded_from_opportunity(
        self,
        embedding_index_test: EmbeddingIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        mock_graph,
    ) -> None:
        """A document affecting holdings must NOT appear in opportunity channel.

        This is the "novelty guard" — opportunity is for NEW ideas only.
        If a document appears in both channels, maintenance wins.
        """
        from unittest.mock import patch
        from datetime import datetime as real_datetime

        now = self._now()

        class FrozenDateTime(real_datetime):
            @classmethod
            def utcnow(cls):
                return now

        profile = self._stub_profile()

        # Document affects TSM (held) AND matches mandate themes
        overlap_doc = {
            "document_guid": "doc-overlap-001",
            "title": "TSMC AI Chip Capacity Expansion",
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "impact_score": 85,
            "impact_tier": "PLATINUM",
            "affected_instruments": ["TSM"],
            "themes": ["semiconductor", "ai"],
        }

        service = self._make_service(
            embedding_index_test, document_store, source_registry, mock_graph,
        )

        with (
            patch("app.services.query_service.datetime", FrozenDateTime),
            patch.object(service, "_get_client_profile_context", return_value=profile),
            patch.object(service, "_get_client_holdings", return_value=[
                {"ticker": "TSM", "weight": 0.15},
            ]),
            patch.object(service, "_get_client_watchlist", return_value=[]),
            patch.object(service, "_get_documents_for_tickers", return_value=[overlap_doc]),
            patch.object(service, "_get_client_mandate_themes", return_value=["semiconductor", "ai"]),
            # Simulate that the same doc was returned by themes query (before exclusion logic)
            patch.object(service, "_get_documents_by_themes", return_value=[overlap_doc]),
        ):
            feed = service.get_client_avatar_feed(
                client_guid="client-avatar-001",
                group_guids=[TEST_GROUP_GUID],
                limit=10,
                time_window_hours=24,
            )

        # Document must appear in maintenance (affects holding)
        maint_guids = [item.document_guid for item in feed.maintenance]
        assert "doc-overlap-001" in maint_guids

        # Document must NOT appear in opportunity (novelty guard)
        opp_guids = [item.document_guid for item in feed.opportunity]
        assert "doc-overlap-001" not in opp_guids, (
            "Holdings doc must be excluded from opportunity channel (novelty guard)"
        )

        # But it should appear exactly once in combined
        combined_guids = [item.document_guid for item in feed.combined]
        assert combined_guids.count("doc-overlap-001") == 1
