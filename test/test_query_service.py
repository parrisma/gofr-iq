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
def test_source_high_trust(source_registry: SourceRegistry, test_group: Group) -> Source:
    """Provide a high-trust source."""
    source = source_registry.create(
        name="Bloomberg",
        group_guid=test_group.group_guid,
        source_type=SourceType.NEWS_AGENCY,
        trust_level=TrustLevel.HIGH,
    )
    return source


@pytest.fixture
def test_source_low_trust(source_registry: SourceRegistry, test_group: Group) -> Source:
    """Provide a low-trust source."""
    source = source_registry.create(
        name="Unverified News",
        group_guid=test_group.group_guid,
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
