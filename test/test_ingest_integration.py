"""Tests for Ingest Service Integration with Indexes.

Tests that IngestService correctly calls EmbeddingIndex and GraphIndex,
and handles failures with rollback.
"""

import uuid
from unittest.mock import MagicMock, patch, ANY

import pytest
from app.models import Source, SourceType, TrustLevel
from app.services import (
    DocumentStore,
    DuplicateDetector,
    EmbeddingIndex,
    GraphIndex,
    IngestService,
    LanguageDetector,
    SourceRegistry,
)
from app.services.graph_index import NodeLabel


@pytest.fixture
def mock_embedding_index():
    index = MagicMock(spec=EmbeddingIndex)
    return index


@pytest.fixture
def mock_graph_index():
    index = MagicMock(spec=GraphIndex)
    return index


@pytest.fixture
def ingest_service_with_indexes(
    tmp_path,
    mock_embedding_index,
    mock_graph_index,
):
    document_store = DocumentStore(base_path=tmp_path / "documents")
    source_registry = SourceRegistry(base_path=tmp_path / "sources")
    
    group_guid = str(uuid.uuid4())
    
    # Create a valid source
    source = source_registry.create(
        name="Test Source",
        group_guid=group_guid,
        source_type=SourceType.NEWS_AGENCY,
        trust_level=TrustLevel.HIGH,
    )
    # We'll use source.source_guid in tests

    service = IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=LanguageDetector(),
        duplicate_detector=DuplicateDetector(),
        embedding_index=mock_embedding_index,
        graph_index=mock_graph_index,
    )
    # Attach source to service for easy access in tests
    service._test_source = source
    service._test_group_guid = group_guid
    return service


def test_ingest_calls_indexes(ingest_service_with_indexes, mock_embedding_index, mock_graph_index):
    """Test that ingest calls embed_document and create_document_node."""
    
    source = ingest_service_with_indexes._test_source
    group_guid = ingest_service_with_indexes._test_group_guid
    
    result = ingest_service_with_indexes.ingest(
        title="Test Document",
        content="This is a test document.",
        source_guid=source.source_guid,
        group_guid=group_guid,
    )

    assert result.is_success

    # Verify EmbeddingIndex was called
    mock_embedding_index.embed_document.assert_called_once()
    call_args = mock_embedding_index.embed_document.call_args
    assert call_args.kwargs["document_guid"] == result.guid
    assert call_args.kwargs["content"] == "This is a test document."

    # Verify GraphIndex was called
    mock_graph_index.create_document_node.assert_called_once()
    call_args = mock_graph_index.create_document_node.call_args
    assert call_args.kwargs["document_guid"] == result.guid
    assert call_args.kwargs["title"] == "Test Document"


def test_ingest_fails_and_rolls_back_on_embedding_error(ingest_service_with_indexes, mock_embedding_index, mock_graph_index):
    """Test that ingest fails and rolls back if embedding fails."""
    
    source = ingest_service_with_indexes._test_source
    group_guid = ingest_service_with_indexes._test_group_guid
    
    # Simulate embedding failure
    mock_embedding_index.embed_document.side_effect = Exception("Embedding failed")

    result = ingest_service_with_indexes.ingest(
        title="Test Document",
        content="This is a test document.",
        source_guid=source.source_guid,
        group_guid=group_guid,
    )

    assert result.is_failed
    assert "Embedding failed" in result.error

    # Verify document was deleted from store
    assert not ingest_service_with_indexes.document_store.exists(result.guid, group_guid)

    # Verify rollback calls
    mock_embedding_index.delete_document.assert_called_once_with(result.guid)
    
    # Graph index creation should NOT be called (since embedding is first)
    mock_graph_index.create_document_node.assert_not_called()
    
    # But rollback calls delete_node
    mock_graph_index.delete_node.assert_called_once_with(NodeLabel.DOCUMENT, result.guid)


def test_ingest_fails_and_rolls_back_on_graph_error(ingest_service_with_indexes, mock_embedding_index, mock_graph_index):
    """Test that ingest fails and rolls back if graph indexing fails."""
    
    source = ingest_service_with_indexes._test_source
    group_guid = ingest_service_with_indexes._test_group_guid
    
    # Simulate graph failure
    mock_graph_index.create_document_node.side_effect = Exception("Graph failed")

    result = ingest_service_with_indexes.ingest(
        title="Test Document",
        content="This is a test document.",
        source_guid=source.source_guid,
        group_guid=group_guid,
    )

    assert result.is_failed
    assert "Graph failed" in result.error

    # Verify document was deleted from store
    assert not ingest_service_with_indexes.document_store.exists(result.guid, group_guid)

    # Verify embedding was called (since it's first)
    mock_embedding_index.embed_document.assert_called_once()

    # Verify rollback calls
    mock_embedding_index.delete_document.assert_called_once_with(result.guid)
    mock_graph_index.delete_node.assert_called_once_with(NodeLabel.DOCUMENT, result.guid)
