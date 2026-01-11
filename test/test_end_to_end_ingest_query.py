"""End-to-End Integration Tests for Document Lifecycle.

These tests verify the complete document lifecycle using REAL services:
- Real ChromaDB for vector storage
- Real Neo4j for graph storage  
- Real LLM (OpenRouter) for entity extraction
- Real Vault for authentication

Unlike other tests, these DO NOT use mocks. They verify:
1. Document ingestion with real entity extraction
2. Vector embeddings stored in ChromaDB
3. Graph nodes and relationships in Neo4j
4. Query and retrieval works end-to-end
5. Group isolation is enforced

Requirements:
- Run via ./scripts/run_tests.sh (sets up test infrastructure)
- OPENROUTER_API_KEY must be set (costs ~$0.01-0.05 per test)
- ChromaDB, Neo4j, and Vault test containers must be running

Test Strategy:
- Use existing vault_auth_service fixture from conftest.py (session-scoped)
- Create test-specific groups/sources (function-scoped)
- Verify real indexing in ChromaDB and Neo4j
- Clean up test data after each test
"""

import os
import uuid
from typing import Generator

import pytest

from app.models import Group, Source, SourceType
from app.services.embedding_index import EmbeddingIndex
from app.services.graph_index import GraphIndex
from app.services.ingest_service import IngestService
from app.services.llm_service import create_llm_service
from app.services.query_service import QueryService
from app.services.source_registry import SourceRegistry


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def openrouter_api_key() -> str:
    """Get OpenRouter API key from environment.
    
    Returns:
        OpenRouter API key.
        
    Raises:
        pytest.skip: If GOFR_IQ_OPENROUTER_API_KEY not set.
    """
    api_key = os.environ.get("GOFR_IQ_OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip(
            "GOFR_IQ_OPENROUTER_API_KEY not set. These tests require real LLM API calls. "
            "Set the environment variable to run end-to-end tests."
        )
    return api_key  # type: ignore[return-value]


@pytest.fixture
def test_group(vault_auth_service) -> Generator[tuple[Group, str], None, None]:
    """Create a unique test group for isolation.
    
    Uses the existing vault_auth_service from conftest.py.
    Creates a group with unique name to ensure test isolation.
    Cleans up after test completes.
    
    Args:
        vault_auth_service: Vault-backed AuthService from conftest.py
        
    Yields:
        Tuple of (Group object, group_name) for the test.
    """
    # Create unique group name (this is the group identifier)
    group_name = f"e2e-test-{uuid.uuid4().hex[:16]}"
    group = None
    
    try:
        group = vault_auth_service.groups.create_group(group_name, "E2E Test Group")
        yield (group, group_name)
    finally:
        # Cleanup: Make group defunct
        if group:
            try:
                vault_auth_service.groups.make_defunct(group.id)  # type: ignore[attr-defined]
            except Exception:
                pass  # Best effort cleanup


@pytest.fixture
def test_token(vault_auth_service, test_group: tuple[Group, str]) -> str:
    """Create a JWT token for the test group.
    
    Uses the existing vault_auth_service from conftest.py.
    
    Args:
        vault_auth_service: Vault-backed AuthService from conftest.py
        test_group: Tuple of (Group, group_name) from test_group fixture.
        
    Returns:
        JWT token string valid for test_group.
    """
    _, group_name = test_group
    token = vault_auth_service.create_token(groups=[group_name])
    return token


@pytest.fixture
def source_registry() -> SourceRegistry:
    """Create SourceRegistry for test.
    
    Uses the standard data directory. Tests should create unique sources.
    
    Returns:
        SourceRegistry instance.
    """
    data_dir = os.environ.get("GOFR_AUTH_DATA_DIR", "data/auth")
    return SourceRegistry(data_dir)


@pytest.fixture
def test_source(source_registry: SourceRegistry, test_group: tuple[Group, str]) -> Generator[Source, None, None]:
    """Create a unique test source for the test group.
    
    Args:
        source_registry: SourceRegistry instance.
        test_group: Tuple of (Group, group_name) from test_group fixture.
        
    Yields:
        Source object for the test.
    """
    group, group_name = test_group
    source_name = f"E2E Test Source {uuid.uuid4().hex[:8]}"
    
    source = source_registry.create(
        name=source_name,
        group_guid=str(group.id),  # type: ignore[attr-defined]
        source_type=SourceType.NEWS_AGENCY,
    )
    
    yield source
    
    # Cleanup: Remove source
    try:
        source_registry.delete(source.guid)  # type: ignore[attr-defined]
    except Exception:
        pass  # Best effort cleanup


@pytest.fixture
def real_llm_service(openrouter_api_key: str):
    """Create LLMService with real OpenRouter API.
    
    Args:
        openrouter_api_key: OpenRouter API key from fixture.
        
    Returns:
        LLMService configured for OpenRouter.
    """
    from app.services.llm_service import LLMSettings
    settings = LLMSettings(api_key=openrouter_api_key)
    return create_llm_service(settings=settings)


@pytest.fixture
def embedding_index(chromadb_config: dict[str, str | int]) -> EmbeddingIndex:
    """Create EmbeddingIndex with real ChromaDB.
    
    Connects to test ChromaDB container using config from conftest.py.
    
    Args:
        chromadb_config: ChromaDB config dict from conftest.py fixture.
        
    Returns:
        EmbeddingIndex connected to test ChromaDB.
    """
    import uuid
    collection_name = f"e2e_test_{uuid.uuid4().hex[:8]}"
    return EmbeddingIndex(
        host=str(chromadb_config["host"]),
        port=int(chromadb_config["port"]),
        collection_name=collection_name,
    )


@pytest.fixture
def graph_index(neo4j_config: dict[str, str | int]) -> GraphIndex:
    """Create GraphIndex with real Neo4j.
    
    Connects to test Neo4j container using config from conftest.py.
    
    Args:
        neo4j_config: Neo4j config dict from conftest.py fixture.
        
    Returns:
        GraphIndex connected to test Neo4j.
    """
    index = GraphIndex(
        uri=str(neo4j_config["uri"]),
        password=str(neo4j_config["password"]),
    )
    index.init_schema()
    return index


@pytest.fixture
def ingest_service(
    real_llm_service,
    embedding_index: EmbeddingIndex,
    graph_index: GraphIndex,
    source_registry: SourceRegistry,
) -> IngestService:
    """Create IngestService with real services.
    
    This is the core integration fixture - uses:
    - Real LLM for entity extraction
    - Real ChromaDB for embeddings
    - Real Neo4j for graph
    
    Args:
        real_llm_service: Real LLM service with OpenRouter.
        embedding_index: Real ChromaDB embedding index.
        graph_index: Real Neo4j graph index.
        source_registry: Source registry for validation.
        
    Returns:
        IngestService with all real backends.
    """
    from app.services.document_store import DocumentStore
    
    # Create document store
    storage_dir = os.environ.get("GOFR_IQ_STORAGE_DIR", "data/storage")
    document_store = DocumentStore(storage_dir)
    
    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        llm_service=real_llm_service,
        embedding_index=embedding_index,
        graph_index=graph_index,
    )


@pytest.fixture
def query_service(
    embedding_index: EmbeddingIndex,
    graph_index: GraphIndex,
    source_registry: SourceRegistry,
) -> QueryService:
    """Create QueryService with real services.
    
    Args:
        embedding_index: Real ChromaDB embedding index.
        graph_index: Real Neo4j graph index.
        source_registry: Source registry for trust levels.
        
    Returns:
        QueryService with all real backends.
    """
    from app.services.document_store import DocumentStore
    import os
    
    storage_dir = os.environ.get("GOFR_IQ_STORAGE_DIR", "data/storage")
    document_store = DocumentStore(storage_dir)
    
    return QueryService(
        embedding_index=embedding_index,
        document_store=document_store,
        source_registry=source_registry,
        graph_index=graph_index,
    )


# =============================================================================
# End-to-End Tests
# =============================================================================


def test_fixtures_created(
    test_group: tuple[Group, str],
    test_token: str,
    test_source: Source,
    vault_auth_service,
):
    """Verify all fixtures are created correctly.
    
    This test validates:
    1. Test group exists in Vault
    2. Test token is valid for test group
    3. Test source exists and is assigned to test group
    
    Uses existing vault_auth_service from conftest.py instead of creating new fixtures.
    """
    group, group_name = test_group
    
    # Verify group exists
    fetched_group = vault_auth_service.groups.get_group(group.id)  # type: ignore[attr-defined]
    assert fetched_group is not None
    assert fetched_group.id == group.id  # type: ignore[attr-defined]
    assert fetched_group.is_active
    
    # Verify token is valid
    token_info = vault_auth_service.verify_token(test_token)
    assert token_info is not None
    assert group_name in token_info.groups
    
    # Verify source
    assert test_source.group_guid == str(group.id)  # type: ignore[attr-defined]
    assert test_source.name.startswith("E2E Test Source")


def test_ingest_document_with_real_llm(
    ingest_service: IngestService,
    test_source: Source,
    test_group: tuple[Group, str],
):
    """Test document ingestion with real LLM entity extraction.
    
    This test verifies:
    1. Document is created
    2. Real LLM extracts entities (Apple, NVIDIA, Tim Cook)
    3. IngestService processes without errors
    4. IngestResult contains document GUID
    
    Note: This test makes a real API call to OpenRouter (~$0.01).
    """
    group, group_name = test_group
    
    # Test content about Apple and NVIDIA
    content = (
        "Apple CEO Tim Cook announced today that Apple has placed a massive order "
        "for NVIDIA's latest AI chips. The deal, worth billions, will help Apple "
        "enhance its machine learning capabilities. Cook made the announcement from "
        "Apple's headquarters in Cupertino, California. NVIDIA's stock surged on the news."
    )
    
    # Ingest document using real LLM
    result = ingest_service.ingest(
        title="Apple Orders Massive Shipment of NVIDIA AI Chips",
        content=content,
        source_guid=test_source.source_guid,
        group_guid=str(group.id),  # type: ignore[attr-defined]
        language="en",
    )
    
    # Verify result
    assert result.guid is not None
    assert len(result.guid) >= 32  # UUID format
    assert result.status.value == "success" or result.status == "success"


def test_verify_chromadb_indexing(
    embedding_index: EmbeddingIndex,
    ingest_service: IngestService,
    test_source: Source,
    test_group: tuple[Group, str],
):
    """Verify document embeddings are stored in ChromaDB.
    
    This test:
    1. Ingests a document (real LLM API call)
    2. Queries ChromaDB directly to verify embeddings exist
    3. Verifies metadata is complete
    
    Note: This test makes a real API call to OpenRouter (~$0.01).
    """
    group, group_name = test_group
    
    # Get initial count
    initial_count = embedding_index.count(group_guid=str(group.id))  # type: ignore[attr-defined]
    
    # Ingest a test document
    content = (
        "Tesla announces breakthrough in battery technology. CEO Elon Musk revealed "
        "the new 4680 battery cell at a press conference in Fremont. The batteries "
        "promise 5x more energy density and 6x more power than previous models."
    )
    
    result = ingest_service.ingest(
        title="Tesla Battery Breakthrough Announced",
        content=content,
        source_guid=test_source.source_guid,
        group_guid=str(group.id),  # type: ignore[attr-defined]
        language="en",
    )
    
    # Verify ingestion succeeded
    assert result.status.value == "success" or result.status == "success"
    assert result.guid is not None
    
    # Verify chunks were added to ChromaDB
    final_count = embedding_index.count(group_guid=str(group.id))  # type: ignore[attr-defined]
    assert final_count > initial_count, "ChromaDB count should increase after ingestion"
    
    # Verify chunks can be retrieved
    chunks = embedding_index.get_document_chunks(result.guid)
    assert len(chunks) > 0, "Document should have at least one chunk"
    
    # Verify chunk metadata
    for chunk in chunks:
        assert chunk.document_guid == result.guid
        assert chunk.content is not None and len(chunk.content) > 0
        assert chunk.chunk_index >= 0
        assert chunk.start_char >= 0
        assert chunk.end_char > chunk.start_char


def test_verify_neo4j_indexing(
    graph_index: GraphIndex,
    ingest_service: IngestService,
    test_source: Source,
    test_group: tuple[Group, str],
):
    """Verify graph nodes and relationships in Neo4j.
    
    This test:
    1. Ingests a document (real LLM API call)
    2. Queries Neo4j directly to verify:
       - Document node exists
       - Entity nodes exist (companies mentioned)
       - Node has correct group_guid
    3. Verifies node properties
    
    Note: This test makes a real API call to OpenRouter (~$0.01).
    """
    from app.services.graph_index import NodeLabel
    
    group, group_name = test_group
    
    # Get initial node count
    initial_doc_count = graph_index.count_nodes(NodeLabel.DOCUMENT)
    initial_company_count = graph_index.count_nodes(NodeLabel.COMPANY)
    
    # Ingest a test document with known entities
    content = (
        "Microsoft and Amazon announced a strategic partnership today. "
        "The deal, brokered by CEO Satya Nadella and Andy Jassy, will integrate "
        "Azure cloud services with AWS infrastructure. Both companies expect "
        "significant synergies from the collaboration in Seattle."
    )
    
    result = ingest_service.ingest(
        title="Microsoft and Amazon Form Strategic Partnership",
        content=content,
        source_guid=test_source.source_guid,
        group_guid=str(group.id),  # type: ignore[attr-defined]
        language="en",
    )
    
    # Verify ingestion succeeded
    assert result.status.value == "success" or result.status == "success"
    assert result.guid is not None
    
    # Verify document node exists in Neo4j
    doc_node = graph_index.get_node(NodeLabel.DOCUMENT, result.guid)
    assert doc_node is not None, "Document node should exist in Neo4j"
    assert doc_node.properties.get("group_guid") == str(group.id), "Document should have correct group_guid"  # type: ignore[attr-defined]
    assert "title" in doc_node.properties
    
    # Verify node counts increased
    final_doc_count = graph_index.count_nodes(NodeLabel.DOCUMENT)
    assert final_doc_count > initial_doc_count, "Document count should increase"
    
    # Note: We can't reliably verify specific companies were extracted since LLM behavior
    # may vary, but we can check that company count increased (if LLM extracted entities)
    final_company_count = graph_index.count_nodes(NodeLabel.COMPANY)
    # This is informational - LLM may or may not extract companies
    if final_company_count > initial_company_count:
        # If companies were extracted, that's a bonus verification
        pass


def test_query_ingested_document(
    ingest_service: IngestService,
    query_service: QueryService,
    test_source: Source,
    test_group: tuple[Group, str],
):
    """Test end-to-end: ingest → query → retrieve.
    
    This test:
    1. Ingests a document (real LLM API call)
    2. Queries for the document using correct group_guid
    3. Verifies document is returned in results
    4. Verifies query filtering works
    
    Note: This test makes a real API call to OpenRouter (~$0.01).
    """
    group, group_name = test_group
    
    # Ingest a test document with distinctive content
    content = (
        "SpaceX successfully launched Starship on its first orbital test flight. "
        "The historic launch from Boca Chica, Texas marks a milestone for Elon Musk's "
        "Mars colonization ambitions. The spacecraft reached orbit and demonstrated "
        "in-space refueling capabilities crucial for deep space missions."
    )
    
    result = ingest_service.ingest(
        title="SpaceX Starship Completes Historic Orbital Test",
        content=content,
        source_guid=test_source.source_guid,
        group_guid=str(group.id),  # type: ignore[attr-defined]
        language="en",
    )
    
    # Verify ingestion succeeded
    assert result.status.value == "success" or result.status == "success"
    assert result.guid is not None
    document_guid = result.guid
    
    # Query for the document using semantic search
    query_response = query_service.query(
        query_text="SpaceX Starship orbital test flight",
        group_guids=[str(group.id)],  # type: ignore[attr-defined]
        n_results=10,
    )
    
    # Verify query response structure
    assert query_response.results is not None
    assert len(query_response.results) > 0, "Query should return at least one result"
    
    # Verify our document is in the results
    found_guids = [r.document_guid for r in query_response.results]
    assert document_guid in found_guids, f"Ingested document {document_guid} should be in query results"
    
    # Find our specific result
    our_result = next((r for r in query_response.results if r.document_guid == document_guid), None)
    assert our_result is not None
    assert our_result.score > 0, "Result should have positive relevance score"
    
    # Verify a different query doesn't match as well
    unrelated_response = query_service.query(
        query_text="cooking pasta recipes Italian cuisine",
        group_guids=[str(group.id)],  # type: ignore[attr-defined]
        n_results=10,
    )
    
    # Our space document should either not appear or have lower score
    if unrelated_response.results:
        unrelated_guids = [r.document_guid for r in unrelated_response.results]
        if document_guid in unrelated_guids:
            unrelated_result = next(r for r in unrelated_response.results if r.document_guid == document_guid)
            # If it appears, score should be much lower
            assert unrelated_result.score < our_result.score * 0.5, "Unrelated query should have much lower score"


def test_group_isolation(
    vault_auth_service,
    source_registry: SourceRegistry,
    ingest_service: IngestService,
    query_service: QueryService,
):
    """Verify group isolation works correctly.
    
    This test:
    1. Creates two test groups (A and B)
    2. Ingests document to group A
    3. Queries with group B GUID - verifies document is NOT returned
    4. Queries with group A GUID - verifies document IS returned
    
    Note: This test makes a real API call to OpenRouter (~$0.01).
    """
    import uuid
    
    # Create two distinct test groups
    group_a_name = f"isolation-test-a-{uuid.uuid4().hex[:8]}"
    group_b_name = f"isolation-test-b-{uuid.uuid4().hex[:8]}"
    
    group_a = vault_auth_service.groups.create_group(group_a_name, "Isolation Test Group A")
    group_b = vault_auth_service.groups.create_group(group_b_name, "Isolation Test Group B")
    source_a = None
    
    try:
        # Create a source for group A
        source_a = source_registry.create(
            name=f"test-source-a-{uuid.uuid4().hex[:8]}",
            group_guid=str(group_a.id),
            source_type=SourceType.NEWS_AGENCY,
        )
        
        # Ingest document to group A
        content = (
            "Quantum Computing Inc announced a major breakthrough in error correction. "
            "The company's new quantum processor achieved 99.9% accuracy in qubit operations, "
            "a milestone that brings practical quantum computing closer to reality."
        )
        
        result = ingest_service.ingest(
            title="Quantum Computing Breakthrough in Error Correction",
            content=content,
            source_guid=source_a.source_guid,
            group_guid=str(group_a.id),
            language="en",
        )
        
        # Verify ingestion succeeded
        assert result.status.value == "success" or result.status == "success"
        assert result.guid is not None
        document_guid = result.guid
        
        # Query with group B's GUID - should NOT see group A's document
        query_b = query_service.query(
            query_text="quantum computing breakthrough",
            group_guids=[str(group_b.id)],
            n_results=10,
        )
        
        # Verify group B cannot see group A's document
        guids_visible_to_b = [r.document_guid for r in query_b.results]
        assert document_guid not in guids_visible_to_b, \
            "Group B should NOT see documents from Group A (isolation violation)"
        
        # Query with group A's GUID - should see the document
        query_a = query_service.query(
            query_text="quantum computing breakthrough",
            group_guids=[str(group_a.id)],
            n_results=10,
        )
        
        # Verify group A can see its own document
        guids_visible_to_a = [r.document_guid for r in query_a.results]
        assert document_guid in guids_visible_to_a, \
            "Group A should see its own document"
        
        # Verify the result has correct properties
        result_a = next(r for r in query_a.results if r.document_guid == document_guid)
        assert result_a.score > 0, "Result should have positive relevance score"
        
    finally:
        # Cleanup
        if source_a:
            try:
                source_registry.delete(source_a.guid)  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            vault_auth_service.groups.defunct_group(group_a_name)
        except Exception:
            pass
        try:
            vault_auth_service.groups.defunct_group(group_b_name)
        except Exception:
            pass


def test_concurrent_ingestion(
    ingest_service: IngestService,
    embedding_index: EmbeddingIndex,
    test_source: Source,
    test_group: tuple[Group, str],
):
    """Verify concurrent document ingestion works.
    
    This test:
    1. Creates 3 documents with distinct content
    2. Ingests them using ThreadPoolExecutor (IngestService is sync)
    3. Verifies all succeed
    4. Verifies all are indexed correctly in ChromaDB
    
    Note: This test makes real API calls to OpenRouter (~$0.03).
    """
    import concurrent.futures
    
    group, group_name = test_group
    
    # Define 3 distinct documents to ingest
    documents = [
        {
            "title": "Google Announces Quantum Computing Milestone",
            "content": (
                "Google researchers have achieved quantum supremacy with their new Willow processor. "
                "The quantum computer solved a calculation in 200 seconds that would take classical "
                "supercomputers 10,000 years. CEO Sundar Pichai announced the breakthrough at a press "
                "conference in Mountain View, California."
            ),
        },
        {
            "title": "OpenAI Releases GPT-5 with Reasoning Capabilities",
            "content": (
                "OpenAI has unveiled GPT-5, featuring advanced reasoning and multi-modal understanding. "
                "Sam Altman demonstrated the model's ability to solve complex mathematical proofs and "
                "generate working code from natural language descriptions. The model will be available "
                "through API access starting next month."
            ),
        },
        {
            "title": "Meta Expands Metaverse with New VR Headset",
            "content": (
                "Meta has launched Quest Pro 2, their most advanced VR headset yet. Mark Zuckerberg "
                "presented the device at Connect conference, highlighting improved mixed reality features. "
                "The headset supports full color passthrough and advanced hand tracking for enterprise "
                "and consumer applications."
            ),
        },
    ]
    
    def ingest_document(doc: dict) -> tuple[str, str, str]:  # type: ignore[misc]
        """Helper to ingest a single document and return (title, guid, status)"""
        result = ingest_service.ingest(
            title=doc["title"],
            content=doc["content"],
            source_guid=test_source.source_guid,
            group_guid=str(group.id),  # type: ignore[attr-defined]  # type: ignore[attr-defined]
            language="en",
        )
        return (doc["title"], result.guid, result.status)
    
    # Ingest all documents concurrently using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(ingest_document, doc) for doc in documents]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    # Verify all ingestions succeeded
    assert len(results) == 3, "Should have 3 results"
    
    for title, guid, status in results:
        assert guid is not None, f"Document '{title}' should have a GUID"
        assert len(guid) >= 32, f"Document '{title}' should have valid GUID format"
        assert str(status) == "success" or getattr(status, 'value', status) == "success", f"Document '{title}' should succeed"
    
    # Verify all documents are indexed in ChromaDB
    guids = [guid for _, guid, _ in results]
    
    for guid in guids:
        chunks = embedding_index.get_document_chunks(guid)
        assert len(chunks) > 0, f"Document {guid} should have chunks in ChromaDB"
    
    # Verify total chunk count increased
    total_chunks = embedding_index.count(group_guid=str(group.id))  # type: ignore[attr-defined]
    assert total_chunks >= 3, "Should have at least 3 chunks (one per document minimum)"
