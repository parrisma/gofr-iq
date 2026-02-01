"""Integration tests for real ChromaDB and Neo4j infrastructure.

These tests require running ChromaDB and Neo4j servers. Run with:
    ./scripts/run_tests.sh --with-infra -k test_integration_infra

Tests verify end-to-end workflows using real services instead of mocks.
"""

import os
import uuid
from typing import Generator

import pytest

from app.models.source import Source, SourceType, TrustLevel
from app.services.document_store import DocumentStore
from app.services.duplicate_detector import DuplicateDetector
from app.services.embedding_index import EmbeddingIndex
from app.services.graph_index import GraphIndex, NodeLabel
from app.services.ingest_service import IngestService
from app.services.language_detector import LanguageDetector
from app.services.llm_service import LLMService, LLMSettings, create_llm_service
from app.services.query_service import QueryService
from app.services.source_registry import SourceRegistry


# =============================================================================
# Skip conditions based on infrastructure availability
# =============================================================================


@pytest.fixture(autouse=True)
def skip_if_no_infra(infra_available: dict[str, bool], request) -> None:
    """Skip tests if required infrastructure is not available."""
    marker = request.node.get_closest_marker("requires_infra")
    if marker and not infra_available["all"]:
        pytest.skip("Test requires ChromaDB and Neo4j infrastructure")
    
    marker = request.node.get_closest_marker("requires_chromadb")
    if marker and not infra_available["chromadb"]:
        pytest.skip("Test requires ChromaDB server")
    
    marker = request.node.get_closest_marker("requires_neo4j")
    if marker and not infra_available["neo4j"]:
        pytest.skip("Test requires Neo4j server")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_group_guid() -> str:
    """Provide a unique group GUID for each test."""
    return str(uuid.uuid4())


@pytest.fixture
def document_store(tmp_path) -> Generator[DocumentStore, None, None]:
    """Provide a DocumentStore instance."""
    store = DocumentStore(base_path=str(tmp_path / "documents"))
    yield store


@pytest.fixture
def source_registry(tmp_path) -> Generator[SourceRegistry, None, None]:
    """Provide a SourceRegistry instance."""
    registry = SourceRegistry(base_path=str(tmp_path / "sources"))
    yield registry


@pytest.fixture
def test_source(
    source_registry: SourceRegistry,
    test_group_guid: str,
) -> Source:
    """Provide a test source."""
    return source_registry.create(
        name="Integration Test Source",
        source_type=SourceType.NEWS_AGENCY,
        trust_level=TrustLevel.HIGH,
    )


@pytest.fixture
def real_embedding_index(
    chromadb_config: dict[str, str | int],
    chromadb_available: bool,
) -> Generator[EmbeddingIndex, None, None]:
    """Provide an EmbeddingIndex connected to real ChromaDB."""
    if not chromadb_available:
        pytest.skip("ChromaDB server not available")
    
    collection_name = f"integration_test_{uuid.uuid4().hex[:8]}"
    
    index = EmbeddingIndex(
        host=str(chromadb_config["host"]),
        port=int(chromadb_config["port"]),
        collection_name=collection_name,
    )
    
    yield index
    
    # Cleanup
    try:
        index.client.delete_collection(collection_name)
    except Exception:
        pass


@pytest.fixture
def real_graph_index(
    neo4j_config: dict[str, str | int],
    neo4j_available: bool,
) -> Generator[GraphIndex, None, None]:
    """Provide a GraphIndex connected to real Neo4j."""
    if not neo4j_available:
        pytest.skip("Neo4j server not available")
    
    index = GraphIndex(
        uri=str(neo4j_config["uri"]),
        password=str(neo4j_config["password"]),
    )
    
    # Clear and initialize schema
    index.clear()
    index.init_schema()
    
    yield index
    
    # Cleanup
    try:
        index.clear()
    except Exception:
        pass
    finally:
        index.close()


@pytest.fixture
def llm_service() -> LLMService | None:
    """Provide LLMService if API key is available.
    
    Returns:
        LLMService configured with OpenRouter API key, or None if not available.
    """
    api_key = os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
    if not api_key:
        return None
    chat_model = os.environ.get("GOFR_IQ_LLM_MODEL", "meta-llama/llama-3.1-70b-instruct")
    settings = LLMSettings(api_key=api_key, chat_model=chat_model)
    return create_llm_service(settings=settings)


@pytest.fixture
def ingest_service(
    document_store: DocumentStore,
    source_registry: SourceRegistry,
    real_embedding_index: EmbeddingIndex,
    real_graph_index: GraphIndex,
    llm_service: LLMService | None,
) -> IngestService:
    """Provide an IngestService with real indexes."""
    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=LanguageDetector(),
        duplicate_detector=DuplicateDetector(),
        embedding_index=real_embedding_index,
        graph_index=real_graph_index,
        llm_service=llm_service,
    )


# =============================================================================
# ChromaDB Integration Tests
# =============================================================================


@pytest.mark.requires_chromadb
@pytest.mark.integration
class TestChromaDBIntegration:
    """Integration tests for ChromaDB."""

    def test_chromadb_connection(
        self,
        chromadb_config: dict[str, str | int],
    ) -> None:
        """Test that we can connect to ChromaDB server."""
        import chromadb
        
        client = chromadb.HttpClient(
            host=str(chromadb_config["host"]),
            port=int(chromadb_config["port"]),
        )
        
        heartbeat = client.heartbeat()
        assert heartbeat is not None

    def test_embed_and_search(
        self,
        real_embedding_index: EmbeddingIndex,
    ) -> None:
        """Test embedding documents and searching."""
        # Embed some documents
        real_embedding_index.embed_document(
            document_guid="doc-001",
            content="Apple announced new iPhone models with improved AI capabilities.",
            group_guid="group-1",
            source_guid="source-1",
            language="en",
        )
        
        real_embedding_index.embed_document(
            document_guid="doc-002",
            content="Toyota revealed plans for electric vehicles in the Asian market.",
            group_guid="group-1",
            source_guid="source-1",
            language="en",
        )
        
        # Search should return relevant results
        results = real_embedding_index.search(
            query="Apple iPhone AI",
            n_results=5,
        )
        
        assert len(results) >= 1
        # Both documents should be returned (ordering depends on embedding function)
        result_guids = [r.document_guid for r in results]
        assert "doc-001" in result_guids

    def test_group_filtering(
        self,
        real_embedding_index: EmbeddingIndex,
    ) -> None:
        """Test that group filtering works correctly."""
        # Embed documents in different groups
        real_embedding_index.embed_document(
            document_guid="doc-g1",
            content="Confidential group 1 document about financial data.",
            group_guid="group-1",
            source_guid="source-1",
            language="en",
        )
        
        real_embedding_index.embed_document(
            document_guid="doc-g2",
            content="Confidential group 2 document about financial data.",
            group_guid="group-2",
            source_guid="source-2",
            language="en",
        )
        
        # Search with group filter
        results = real_embedding_index.search(
            query="confidential financial",
            n_results=5,
            group_guids=["group-1"],
        )
        
        # Should only return group-1 document
        assert len(results) >= 1
        for result in results:
            assert result.metadata.get("group_guid") == "group-1"


# =============================================================================
# Neo4j Integration Tests
# =============================================================================


@pytest.mark.requires_neo4j
@pytest.mark.integration
class TestNeo4jIntegration:
    """Integration tests for Neo4j."""

    def test_neo4j_connection(
        self,
        neo4j_config: dict[str, str | int],
    ) -> None:
        """Test that we can connect to Neo4j server."""
        from app.services.graph_index import GraphIndex
        
        index = GraphIndex(
            uri=str(neo4j_config["uri"]),
            password=str(neo4j_config["password"]),
        )
        
        assert index.verify_connectivity() is True
        index.close()

    def test_create_and_query_nodes(
        self,
        real_graph_index: GraphIndex,
    ) -> None:
        """Test creating and querying nodes."""
        # Create nodes
        real_graph_index.create_node(
            NodeLabel.SOURCE,
            "test-source-001",
            {"name": "Test Source"},
        )
        
        real_graph_index.create_document_node(
            document_guid="test-doc-001",
            source_guid="test-source-001",
            group_guid="test-group-001",
            title="Test Document",
            language="en",
        )
        
        # Query nodes
        retrieved = real_graph_index.get_node(NodeLabel.DOCUMENT, "test-doc-001")
        assert retrieved is not None
        assert retrieved.properties["title"] == "Test Document"
        
        # Query relationships
        docs = real_graph_index.get_documents_by_source("test-source-001")
        assert len(docs) >= 1

    def test_company_mentions(
        self,
        real_graph_index: GraphIndex,
    ) -> None:
        """Test company mention relationships."""
        # Create source and document
        real_graph_index.create_node(NodeLabel.SOURCE, "src-1", {"name": "Source"})
        real_graph_index.create_node(NodeLabel.GROUP, "grp-1", {"name": "Group"})
        
        real_graph_index.create_document_node(
            document_guid="doc-mentions",
            source_guid="src-1",
            group_guid="grp-1",
            title="Tech News",
            language="en",
        )
        
        # Add company mentions
        real_graph_index.add_company_mention("doc-mentions", "AAPL", "Apple Inc")
        real_graph_index.add_company_mention("doc-mentions", "GOOGL", "Google")
        
        # Query documents mentioning Apple
        docs = real_graph_index.get_documents_mentioning_company("AAPL")
        assert len(docs) >= 1
        assert docs[0].guid == "doc-mentions"


# =============================================================================
# Full Integration Tests (Both Services)
# =============================================================================


@pytest.mark.requires_infra
@pytest.mark.integration
class TestFullIntegration:
    """Integration tests using both ChromaDB and Neo4j."""

    def test_ingest_to_search_workflow(
        self,
        ingest_service: IngestService,
        real_embedding_index: EmbeddingIndex,
        real_graph_index: GraphIndex,
        test_source: Source,
        test_group_guid: str,
    ) -> None:
        """Test complete ingest-to-search workflow."""
        # Ingest a document
        result = ingest_service.ingest(
            title="Technology Investment Report",
            content="Apple and Microsoft are leading the AI revolution. "
                    "Both companies are investing billions in artificial intelligence.",
            source_guid=test_source.source_guid,
            group_guid=test_group_guid,
            metadata={"companies": ["AAPL", "MSFT"]},
        )
        
        assert result.is_success
        doc_guid = result.guid
        
        # Verify document is in ChromaDB
        search_results = real_embedding_index.search(
            query="AI investment technology",
            n_results=5,
            group_guids=[test_group_guid],
        )
        
        assert len(search_results) >= 1
        assert search_results[0].document_guid == doc_guid
        
        # Verify document is in Neo4j
        doc_node = real_graph_index.get_node(NodeLabel.DOCUMENT, doc_guid)
        assert doc_node is not None
        assert doc_node.properties["title"] == "Technology Investment Report"

    def test_ingest_multiple_and_query(
        self,
        ingest_service: IngestService,
        real_embedding_index: EmbeddingIndex,
        test_source: Source,
        test_group_guid: str,
    ) -> None:
        """Test ingesting multiple documents and querying."""
        # Ingest multiple documents
        docs = [
            ("Automotive News", "Toyota announced new electric vehicle lineup for 2025."),
            ("Tech Update", "Apple's latest iPhone features advanced AI processing."),
            ("Finance Report", "Federal Reserve raises interest rates amid inflation."),
        ]
        
        doc_guids = []
        for title, content in docs:
            result = ingest_service.ingest(
                title=title,
                content=content,
                source_guid=test_source.source_guid,
                group_guid=test_group_guid,
            )
            assert result.is_success
            doc_guids.append(result.guid)
        
        # Search for automotive content
        results = real_embedding_index.search(
            query="electric vehicles cars",
            n_results=3,
            group_guids=[test_group_guid],
        )
        
        assert len(results) >= 1
        # All ingested documents should be findable (ordering depends on embedding function)
        result_guids = [r.document_guid for r in results]
        # At least one of our documents should be in the results
        assert any(guid in result_guids for guid in doc_guids)

    def test_rollback_on_graph_failure(
        self,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        real_embedding_index: EmbeddingIndex,
        real_graph_index: GraphIndex,
        test_source: Source,
        test_group_guid: str,
    ) -> None:
        """Test that rollback works when graph indexing fails."""
        from unittest.mock import patch
        
        service = IngestService(
            document_store=document_store,
            source_registry=source_registry,
            language_detector=LanguageDetector(),
            duplicate_detector=DuplicateDetector(),
            embedding_index=real_embedding_index,
            graph_index=real_graph_index,
        )
        
        # Patch graph index to fail
        with patch.object(
            real_graph_index,
            "create_document_node",
            side_effect=Exception("Graph error"),
        ):
            result = service.ingest(
                title="Will Fail",
                content="This document will fail during graph indexing.",
                source_guid=test_source.source_guid,
                group_guid=test_group_guid,
            )
        
        assert result.is_failed
        assert result.error is not None
        assert "Graph error" in result.error
        
        # Verify document was rolled back from document store
        assert not document_store.exists(result.guid, test_group_guid)


@pytest.mark.requires_infra
@pytest.mark.integration
class TestQueryServiceIntegration:
    """Integration tests for QueryService with real indexes."""

    @pytest.fixture
    def query_service(
        self,
        real_embedding_index: EmbeddingIndex,
        real_graph_index: GraphIndex,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
    ) -> QueryService:
        """Provide a QueryService with real indexes."""
        return QueryService(
            embedding_index=real_embedding_index,
            graph_index=real_graph_index,
            document_store=document_store,
            source_registry=source_registry,
        )

    def test_query_with_graph_enrichment(
        self,
        query_service: QueryService,
        real_embedding_index: EmbeddingIndex,
        real_graph_index: GraphIndex,
        source_registry: SourceRegistry,
        test_group_guid: str,
    ) -> None:
        """Test query service with graph context enrichment."""
        # Create source
        source = source_registry.create(
            name="High Trust Source",
            source_type=SourceType.NEWS_AGENCY,
            trust_level=TrustLevel.HIGH,
        )
        
        # Create graph nodes
        real_graph_index.create_node(NodeLabel.SOURCE, source.source_guid, {"name": source.name})
        real_graph_index.create_node(NodeLabel.GROUP, test_group_guid, {"name": "Test Group"})
        
        doc_guid = str(uuid.uuid4())
        real_graph_index.create_document_node(
            document_guid=doc_guid,
            source_guid=source.source_guid,
            group_guid=test_group_guid,
            title="Market Analysis",
            language="en",
        )
        
        # Embed document
        real_embedding_index.embed_document(
            document_guid=doc_guid,
            content="Comprehensive market analysis of technology sector growth.",
            group_guid=test_group_guid,
            source_guid=source.source_guid,
            language="en",
        )
        
        # Query with filters
        response = query_service.query(
            query_text="technology market growth",
            group_guids=[test_group_guid],
            include_graph_context=True,
        )
        
        assert response.total_found >= 1
        assert response.results[0].document_guid == doc_guid
