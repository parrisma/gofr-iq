"""Tests for Document Hard Delete Feature.

Tests for complete document deletion from all storage layers:
- Document store (canonical files)
- Embedding index (ChromaDB vectors)
- Graph index (Neo4j nodes)

Phase: Document Hard Delete Feature
See: docs/features/DOCUMENT_HARD_DELETE_PROPOSAL.md
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models import Document, Source, SourceType, TrustLevel
from app.services import (
    AuditEventType,
    AuditService,
    DocumentStore,
    DuplicateDetector,
    IngestService,
    LanguageDetector,
    SourceRegistry,
    log_document_delete,
)
from app.services.document_store import DocumentNotFoundError


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def storage_path(tmp_path: Path) -> Path:
    """Create temporary storage path."""
    return tmp_path


@pytest.fixture
def document_store(storage_path: Path) -> DocumentStore:
    """Create document store."""
    return DocumentStore(base_path=storage_path / "documents")


@pytest.fixture
def source_registry(storage_path: Path) -> SourceRegistry:
    """Create source registry."""
    return SourceRegistry(base_path=storage_path / "sources")


@pytest.fixture
def language_detector() -> LanguageDetector:
    """Create language detector."""
    return LanguageDetector()


@pytest.fixture
def duplicate_detector() -> DuplicateDetector:
    """Create duplicate detector."""
    return DuplicateDetector()


@pytest.fixture
def audit_service(storage_path: Path) -> AuditService:
    """Create audit service."""
    return AuditService(base_path=storage_path / "audit")


@pytest.fixture
def group_guid() -> str:
    """Create a test group GUID."""
    return str(uuid.uuid4())


@pytest.fixture
def source(source_registry: SourceRegistry) -> Source:
    """Create a test source."""
    return source_registry.create(
        name="Test Source",
        source_type=SourceType.NEWS_AGENCY,
        region="APAC",
        languages=["en"],
        trust_level=TrustLevel.HIGH,
    )


@pytest.fixture
def ingest_service(
    document_store: DocumentStore,
    source_registry: SourceRegistry,
    language_detector: LanguageDetector,
    duplicate_detector: DuplicateDetector,
) -> IngestService:
    """Create ingest service with all dependencies."""
    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=language_detector,
        duplicate_detector=duplicate_detector,
    )


@pytest.fixture
def sample_document(document_store: DocumentStore, source: Source, group_guid: str) -> Document:
    """Create and save a sample document for testing deletion."""
    doc = Document(
        source_guid=source.source_guid,
        group_guid=group_guid,
        title="Test Document for Deletion",
        content="This is test content that will be deleted.",
    )
    document_store.save(doc)
    return doc


# =============================================================================
# DOCUMENT STORE DELETE TESTS
# =============================================================================


class TestDocumentStoreDelete:
    """Tests for DocumentStore.delete() method."""

    def test_delete_document_success(
        self, document_store: DocumentStore, sample_document: Document
    ) -> None:
        """Test successful deletion of an existing document."""
        # Verify document exists before deletion
        assert document_store.exists(sample_document.guid, sample_document.group_guid)

        # Delete the document
        result = document_store.delete(sample_document.guid, sample_document.group_guid)

        # Verify deletion was successful
        assert result is True
        assert not document_store.exists(sample_document.guid, sample_document.group_guid)

    def test_delete_nonexistent_document_returns_false(
        self, document_store: DocumentStore, group_guid: str
    ) -> None:
        """Test deleting a non-existent document returns False."""
        fake_guid = str(uuid.uuid4())

        result = document_store.delete(fake_guid, group_guid)

        assert result is False

    def test_delete_with_date_hint(
        self, document_store: DocumentStore, source: Source, group_guid: str
    ) -> None:
        """Test deletion with date hint for faster lookup."""
        # Create document with specific date
        now = datetime.now(UTC)
        doc = Document(
            source_guid=source.source_guid,
            group_guid=group_guid,
            title="Test with Date",
            content="Content for date test.",
            created_at=now,
        )
        document_store.save(doc)

        # Delete with date hint
        date_str = now.strftime("%Y-%m-%d")
        result = document_store.delete(doc.guid, doc.group_guid, date_str)

        assert result is True
        assert not document_store.exists(doc.guid, doc.group_guid)

    def test_delete_removes_file_from_disk(
        self, document_store: DocumentStore, source: Source, group_guid: str, storage_path: Path
    ) -> None:
        """Test that delete actually removes the file from disk."""
        # Create a fresh document so we know the exact path
        doc = Document(
            source_guid=source.source_guid,
            group_guid=group_guid,
            title="Test Document for Deletion",
            content="This is test content that will be deleted.",
        )
        document_store.save(doc)
        
        # Get expected file path - DocumentStore uses base_path/documents/group/date/guid.json
        # Our fixture creates DocumentStore with base_path=storage_path/documents
        # So actual path is: storage_path/documents/documents/group/date/guid.json
        date_str = doc.created_at.strftime("%Y-%m-%d")
        doc_path = (
            storage_path
            / "documents"  # base_path 
            / "documents"  # _documents_path subdirectory added by DocumentStore
            / doc.group_guid
            / date_str
            / f"{doc.guid}.json"
        )

        # Verify file exists
        assert doc_path.exists(), f"Document file should exist at {doc_path}"

        # Delete document
        document_store.delete(doc.guid, doc.group_guid)

        # Verify file is gone
        assert not doc_path.exists()


# =============================================================================
# AUDIT SERVICE DELETE TESTS
# =============================================================================


class TestAuditServiceDocumentDelete:
    """Tests for audit logging of document deletion."""

    def test_log_document_delete_creates_entry(
        self, audit_service: AuditService, group_guid: str
    ) -> None:
        """Test that log_document_delete creates an audit entry."""
        document_guid = str(uuid.uuid4())

        entry = log_document_delete(
            service=audit_service,
            document_guid=document_guid,
            group_guid=group_guid,
            title="Test Document",
            actor="admin",
            deleted_from=["document_store", "embedding_index", "graph_index"],
            vector_chunks_deleted=15,
        )

        assert entry.event_type == AuditEventType.DOCUMENT_DELETE
        assert entry.resource_guid == document_guid
        assert entry.resource_type == "document"
        assert entry.group_guid == group_guid
        assert entry.actor == "admin"
        assert entry.details["operation"] == "hard_delete"
        assert entry.details["title"] == "Test Document"
        assert entry.details["deleted_from"] == ["document_store", "embedding_index", "graph_index"]
        assert entry.details["vector_chunks_deleted"] == 15

    def test_log_document_delete_persists_to_storage(
        self, audit_service: AuditService, storage_path: Path, group_guid: str
    ) -> None:
        """Test that deletion audit entry is persisted to storage."""
        document_guid = str(uuid.uuid4())

        log_document_delete(
            service=audit_service,
            document_guid=document_guid,
            group_guid=group_guid,
            actor="test-admin",
        )

        # Check audit log file exists
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        audit_path = storage_path / "audit" / today / "audit.jsonl"
        assert audit_path.exists()

        # Read and verify log entry
        with open(audit_path) as f:
            lines = f.readlines()
            assert len(lines) >= 1
            entry = json.loads(lines[-1])
            assert entry["event_type"] == "document.delete"
            assert entry["resource_guid"] == document_guid

    def test_log_document_delete_without_optional_fields(
        self, audit_service: AuditService, group_guid: str
    ) -> None:
        """Test log_document_delete works without optional fields."""
        document_guid = str(uuid.uuid4())

        entry = log_document_delete(
            service=audit_service,
            document_guid=document_guid,
            group_guid=group_guid,
        )

        assert entry.event_type == AuditEventType.DOCUMENT_DELETE
        assert entry.resource_guid == document_guid
        assert entry.details["operation"] == "hard_delete"
        # Optional fields should not be present
        assert "title" not in entry.details
        assert "deleted_from" not in entry.details


# =============================================================================
# INGEST SERVICE DELETE INTEGRATION TESTS
# =============================================================================


class TestIngestServiceDeleteIntegration:
    """Integration tests for document deletion through IngestService."""

    def test_delete_from_document_store_via_service(
        self, ingest_service: IngestService, source: Source, group_guid: str
    ) -> None:
        """Test deletion from document store via ingest service reference."""
        # Ingest a document
        result = ingest_service.ingest(
            title="Document to Delete",
            content="This content will be deleted.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.is_success
        doc_guid = result.guid

        # Verify document exists
        assert ingest_service.document_store.exists(doc_guid, group_guid)

        # Delete via document store
        deleted = ingest_service.document_store.delete(doc_guid, group_guid)

        assert deleted is True
        assert not ingest_service.document_store.exists(doc_guid, group_guid)


# =============================================================================
# MCP TOOL DELETE TESTS (MOCKED)
# =============================================================================


class TestDeleteDocumentMcpTool:
    """Tests for delete_document MCP tool using mocks."""

    def test_delete_requires_confirmation(self) -> None:
        """Test that delete tool requires confirm=true."""
        from app.tools.ingest_tools import register_ingest_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        mock_service = MagicMock(spec=IngestService)
        register_ingest_tools(mcp, mock_service)

        # Get the delete_document tool
        delete_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "delete_document":
                delete_tool = tool
                break

        assert delete_tool is not None
        assert "confirm" in delete_tool.description.lower()

    def test_delete_requires_admin_in_description(self) -> None:
        """Test that delete tool description mentions admin requirement."""
        from app.tools.ingest_tools import register_ingest_tools
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        mock_service = MagicMock(spec=IngestService)
        register_ingest_tools(mcp, mock_service)

        # Get the delete_document tool
        delete_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "delete_document":
                delete_tool = tool
                break

        assert delete_tool is not None
        assert "admin" in delete_tool.description.lower()


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestDeleteEdgeCases:
    """Tests for edge cases in document deletion."""

    def test_delete_document_idempotent(
        self, document_store: DocumentStore, sample_document: Document
    ) -> None:
        """Test that deleting same document twice doesn't error."""
        # First delete succeeds
        result1 = document_store.delete(sample_document.guid, sample_document.group_guid)
        assert result1 is True

        # Second delete returns False (already deleted)
        result2 = document_store.delete(sample_document.guid, sample_document.group_guid)
        assert result2 is False

    def test_delete_with_wrong_group_guid_fails(
        self, document_store: DocumentStore, sample_document: Document
    ) -> None:
        """Test that deleting with wrong group_guid fails."""
        wrong_group = str(uuid.uuid4())

        result = document_store.delete(sample_document.guid, wrong_group)

        # Should return False - document not found in that group
        assert result is False
        # Original should still exist
        assert document_store.exists(sample_document.guid, sample_document.group_guid)

    def test_load_deleted_document_raises_error(
        self, document_store: DocumentStore, sample_document: Document
    ) -> None:
        """Test that loading a deleted document raises DocumentNotFoundError."""
        # Delete the document
        document_store.delete(sample_document.guid, sample_document.group_guid)

        # Try to load it
        with pytest.raises(DocumentNotFoundError):
            document_store.load(sample_document.guid, sample_document.group_guid)


# =============================================================================
# EMBEDDING INDEX DELETE TESTS (MOCKED)
# =============================================================================


class TestEmbeddingIndexDelete:
    """Tests for embedding index deletion (using mocks for ChromaDB)."""

    def test_embedding_delete_returns_chunk_count(self) -> None:
        """Test that embedding delete returns count of deleted chunks."""
        from app.services.embedding_index import EmbeddingIndex

        # Create mock embedding index
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["chunk1", "chunk2", "chunk3"],
            "documents": None,
            "metadatas": None,
        }
        mock_collection.delete.return_value = None

        # Patch the EmbeddingIndex
        with patch.object(EmbeddingIndex, "__init__", return_value=None):
            index = EmbeddingIndex.__new__(EmbeddingIndex)
            index._collection = mock_collection
            index._client = MagicMock()

            document_guid = str(uuid.uuid4())
            count = index.delete_document(document_guid)

            assert count == 3
            mock_collection.delete.assert_called_once_with(
                ids=["chunk1", "chunk2", "chunk3"]
            )

    def test_embedding_delete_nonexistent_returns_zero(self) -> None:
        """Test that deleting non-existent document returns 0 chunks."""
        from app.services.embedding_index import EmbeddingIndex

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": [],
            "documents": None,
            "metadatas": None,
        }

        with patch.object(EmbeddingIndex, "__init__", return_value=None):
            index = EmbeddingIndex.__new__(EmbeddingIndex)
            index._collection = mock_collection
            index._client = MagicMock()

            document_guid = str(uuid.uuid4())
            count = index.delete_document(document_guid)

            assert count == 0
            mock_collection.delete.assert_not_called()


# =============================================================================
# GRAPH INDEX DELETE TESTS (MOCKED)
# =============================================================================


class TestGraphIndexDelete:
    """Tests for graph index deletion (using mocks for Neo4j)."""

    def test_graph_delete_returns_true_on_success(self) -> None:
        """Test that graph delete returns True when node is deleted."""
        from app.services.graph_index import GraphIndex, NodeLabel

        # Create mock session
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_record = {"deleted": 1}
        mock_result.single.return_value = mock_record
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)

        with patch.object(GraphIndex, "__init__", return_value=None):
            index = GraphIndex.__new__(GraphIndex)
            index._driver = MagicMock()
            index._driver.session.return_value = mock_session

            with patch.object(index, "_get_session", return_value=mock_session):
                document_guid = str(uuid.uuid4())
                result = index.delete_node(NodeLabel.DOCUMENT, document_guid)

            assert result is True

    def test_graph_delete_returns_false_when_not_found(self) -> None:
        """Test that graph delete returns False when node not found."""
        from app.services.graph_index import GraphIndex, NodeLabel

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_record = {"deleted": 0}
        mock_result.single.return_value = mock_record
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)

        with patch.object(GraphIndex, "__init__", return_value=None):
            index = GraphIndex.__new__(GraphIndex)
            index._driver = MagicMock()
            index._driver.session.return_value = mock_session

            with patch.object(index, "_get_session", return_value=mock_session):
                document_guid = str(uuid.uuid4())
                result = index.delete_node(NodeLabel.DOCUMENT, document_guid)

            assert result is False


# =============================================================================
# COMPLETE DELETE WORKFLOW TESTS
# =============================================================================


class TestCompleteDeleteWorkflow:
    """Tests for the complete delete workflow across all layers."""

    def test_complete_delete_workflow_document_store_only(
        self, ingest_service: IngestService, source: Source, group_guid: str
    ) -> None:
        """Test complete delete workflow with document store only."""
        # Step 1: Ingest a document
        result = ingest_service.ingest(
            title="Complete Delete Test",
            content="Content for complete delete test workflow.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )
        assert result.is_success
        doc_guid = result.guid

        # Step 2: Verify document exists
        doc = ingest_service.document_store.load(doc_guid, group_guid)
        assert doc.title == "Complete Delete Test"

        # Step 3: Delete from document store
        deleted = ingest_service.document_store.delete(doc_guid, group_guid)
        assert deleted is True

        # Step 4: Verify document is gone
        with pytest.raises(DocumentNotFoundError):
            ingest_service.document_store.load(doc_guid, group_guid)

        # Note: Audit logging would be done by the MCP tool layer, not IngestService

    def test_delete_multiple_documents(
        self, document_store: DocumentStore, source: Source, group_guid: str
    ) -> None:
        """Test deleting multiple documents sequentially."""
        docs = []
        for i in range(5):
            doc = Document(
                source_guid=source.source_guid,
                group_guid=group_guid,
                title=f"Document {i}",
                content=f"Content for document {i}.",
            )
            document_store.save(doc)
            docs.append(doc)

        # Verify all exist
        for doc in docs:
            assert document_store.exists(doc.guid, doc.group_guid)

        # Delete all
        for doc in docs:
            result = document_store.delete(doc.guid, doc.group_guid)
            assert result is True

        # Verify all deleted
        for doc in docs:
            assert not document_store.exists(doc.guid, doc.group_guid)
