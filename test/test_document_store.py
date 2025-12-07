"""Tests for DocumentStore - Phase 2 of implementation.

This module tests the canonical document store with:
- Basic save/load operations
- Path partitioning by group/date
- Document versioning
- Listing documents by group/date

Phase 2 Steps:
    2.1 - Basic save/load
    2.2 - Path partitioning: group/date/guid.json
    2.3 - Document versioning (link to previous)
    2.4 - List documents by group/date
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.models import Document, DocumentCreate
from app.services import DocumentNotFoundError, DocumentStore


class TestDocumentStoreSaveLoad:
    """Tests for basic save/load operations - Phase 2, Step 2.1"""

    def test_save_document(self, tmp_path: Path) -> None:
        """Test saving a document creates a file."""
        store = DocumentStore(tmp_path)
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test Document",
            content="This is test content.",
        )

        result_path = store.save(doc)

        assert result_path.exists()
        assert result_path.suffix == ".json"
        assert doc.guid in result_path.name

    def test_load_document(self, tmp_path: Path) -> None:
        """Test loading a saved document."""
        store = DocumentStore(tmp_path)
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test Document",
            content="This is test content.",
            metadata={"author": "Test Author"},
        )
        store.save(doc)

        loaded = store.load(doc.guid, doc.group_guid)

        assert loaded.guid == doc.guid
        assert loaded.title == doc.title
        assert loaded.content == doc.content
        assert loaded.metadata["author"] == "Test Author"

    def test_load_nonexistent_raises_not_found(self, tmp_path: Path) -> None:
        """Test loading non-existent document raises error."""
        store = DocumentStore(tmp_path)

        with pytest.raises(DocumentNotFoundError) as exc_info:
            store.load("nonexistent-guid", "a1b2c3d4-e5f6-7890-abcd-ef1234567890")

        assert "nonexistent-guid" in str(exc_info.value)

    def test_exists_returns_true_for_saved(self, tmp_path: Path) -> None:
        """Test exists returns True for saved documents."""
        store = DocumentStore(tmp_path)
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
        )
        store.save(doc)

        assert store.exists(doc.guid, doc.group_guid) is True

    def test_exists_returns_false_for_nonexistent(self, tmp_path: Path) -> None:
        """Test exists returns False for non-existent documents."""
        store = DocumentStore(tmp_path)

        assert store.exists("nonexistent", "group") is False

    def test_delete_document(self, tmp_path: Path) -> None:
        """Test deleting a document."""
        store = DocumentStore(tmp_path)
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
        )
        store.save(doc)

        result = store.delete(doc.guid, doc.group_guid)

        assert result is True
        assert store.exists(doc.guid, doc.group_guid) is False

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        """Test deleting non-existent document returns False."""
        store = DocumentStore(tmp_path)

        result = store.delete("nonexistent", "group")

        assert result is False

    def test_create_from_input(self, tmp_path: Path) -> None:
        """Test creating document from DocumentCreate input."""
        store = DocumentStore(tmp_path)
        create_input = DocumentCreate(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="New Document",
            content="This is the document content with multiple words.",
            metadata={"key": "value"},
        )

        doc = store.create_from_input(create_input, language="en")

        assert doc.guid is not None
        assert doc.title == "New Document"
        assert doc.word_count == 8
        assert doc.language == "en"
        assert store.exists(doc.guid, doc.group_guid)


class TestDocumentStorePathStructure:
    """Tests for path partitioning - Phase 2, Step 2.2"""

    def test_document_path_structure(self, tmp_path: Path) -> None:
        """Test documents are stored in group/date/guid.json structure."""
        store = DocumentStore(tmp_path)
        now = datetime.now(UTC)
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
            created_at=now,
        )

        result_path = store.save(doc)

        # Check path structure
        expected_date = now.strftime("%Y-%m-%d")
        assert doc.group_guid in str(result_path)
        assert expected_date in str(result_path)
        assert f"{doc.guid}.json" in str(result_path)

        # Verify relative structure
        relative_path = result_path.relative_to(tmp_path)
        parts = relative_path.parts
        assert parts[0] == "documents"
        assert parts[1] == doc.group_guid
        assert parts[2] == expected_date
        assert parts[3] == f"{doc.guid}.json"

    def test_documents_partitioned_by_group(self, tmp_path: Path) -> None:
        """Test documents are partitioned by group GUID."""
        store = DocumentStore(tmp_path)

        doc1 = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="b1c2d3e4-f5a6-7890-abcd-ef1234567890",
            title="Group Alpha Doc",
            content="Content",
        )
        doc2 = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="c1d2e3f4-a5b6-7890-abcd-ef1234567890",
            title="Group Beta Doc",
            content="Content",
        )

        path1 = store.save(doc1)
        path2 = store.save(doc2)

        # Should be in different group directories
        assert doc1.group_guid in str(path1)
        assert doc2.group_guid in str(path2)
        assert str(path1.parent.parent) != str(path2.parent.parent)

    def test_documents_partitioned_by_date(self, tmp_path: Path) -> None:
        """Test documents are partitioned by date."""
        store = DocumentStore(tmp_path)
        now = datetime.now(UTC)
        yesterday = now - timedelta(days=1)

        doc1 = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Today Doc",
            content="Content",
            created_at=now,
        )
        doc2 = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Yesterday Doc",
            content="Content",
            created_at=yesterday,
        )

        path1 = store.save(doc1)
        path2 = store.save(doc2)

        # Should be in different date directories
        today_str = now.strftime("%Y-%m-%d")
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        assert today_str in str(path1)
        assert yesterday_str in str(path2)

    def test_load_with_date_hint(self, tmp_path: Path) -> None:
        """Test loading with date hint is faster (direct path)."""
        store = DocumentStore(tmp_path)
        now = datetime.now(UTC)
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
            created_at=now,
        )
        store.save(doc)

        # Load with date hint
        loaded = store.load(doc.guid, doc.group_guid, date=now)

        assert loaded.guid == doc.guid

    def test_load_with_date_string_hint(self, tmp_path: Path) -> None:
        """Test loading with date string hint."""
        store = DocumentStore(tmp_path)
        now = datetime.now(UTC)
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
            created_at=now,
        )
        store.save(doc)

        # Load with date string hint
        date_str = now.strftime("%Y-%m-%d")
        loaded = store.load(doc.guid, doc.group_guid, date=date_str)

        assert loaded.guid == doc.guid


class TestDocumentVersioning:
    """Tests for document versioning - Phase 2, Step 2.3"""

    def test_document_version_chain(self, tmp_path: Path) -> None:
        """Test creating version chain from document."""
        store = DocumentStore(tmp_path)

        # Create v1
        v1 = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Original Title",
            content="Original content.",
        )
        store.save(v1)

        # Create v2
        v2 = store.save_version(v1, {"title": "Updated Title"})

        assert v2.version == 2
        assert v2.previous_version_guid == v1.guid
        assert v2.title == "Updated Title"
        assert v2.content == "Original content."
        assert store.exists(v2.guid, v2.group_guid)

    def test_get_version_chain(self, tmp_path: Path) -> None:
        """Test retrieving full version chain."""
        store = DocumentStore(tmp_path)

        # Create version chain
        v1 = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="v1",
            content="Content",
        )
        store.save(v1)

        v2 = store.save_version(v1, {"title": "v2"})
        v3 = store.save_version(v2, {"title": "v3"})

        # Get chain from any version
        chain = store.get_version_chain(v3.guid, v3.group_guid)

        assert len(chain) == 3
        assert chain[0].guid == v1.guid  # Oldest first
        assert chain[1].guid == v2.guid
        assert chain[2].guid == v3.guid

    def test_version_preserves_metadata(self, tmp_path: Path) -> None:
        """Test that versioning preserves and merges metadata."""
        store = DocumentStore(tmp_path)

        v1 = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Title",
            content="Content",
            metadata={"author": "John", "status": "draft"},
        )
        store.save(v1)

        v2 = store.save_version(v1, {"metadata": {"status": "published"}})

        assert v2.metadata["author"] == "John"  # Preserved
        assert v2.metadata["status"] == "published"  # Updated


class TestDocumentListOperations:
    """Tests for listing documents - Phase 2, Step 2.4"""

    def test_list_documents_by_group(self, tmp_path: Path) -> None:
        """Test listing documents in a group."""
        store = DocumentStore(tmp_path)
        group_guid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        # Create documents in group
        docs = []
        for i in range(5):
            doc = Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid=group_guid,
                title=f"Document {i}",
                content=f"Content {i}",
            )
            store.save(doc)
            docs.append(doc)

        # List group documents
        result = store.list_by_group(group_guid)

        assert len(result) == 5
        result_guids = {d.guid for d in result}
        expected_guids = {d.guid for d in docs}
        assert result_guids == expected_guids

    def test_list_documents_by_group_empty(self, tmp_path: Path) -> None:
        """Test listing documents in empty group."""
        store = DocumentStore(tmp_path)

        result = store.list_by_group("empty-group")

        assert result == []

    def test_list_documents_with_limit(self, tmp_path: Path) -> None:
        """Test listing documents with limit."""
        store = DocumentStore(tmp_path)
        group_guid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        # Create 10 documents
        for i in range(10):
            doc = Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid=group_guid,
                title=f"Document {i}",
                content=f"Content {i}",
            )
            store.save(doc)

        # List with limit
        result = store.list_by_group(group_guid, limit=3)

        assert len(result) == 3

    def test_list_documents_by_date(self, tmp_path: Path) -> None:
        """Test listing documents filtered by date."""
        store = DocumentStore(tmp_path)
        group_guid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        today = datetime.now(UTC)
        yesterday = today - timedelta(days=1)

        # Create documents on different dates
        today_doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid=group_guid,
            title="Today",
            content="Content",
            created_at=today,
        )
        yesterday_doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid=group_guid,
            title="Yesterday",
            content="Content",
            created_at=yesterday,
        )
        store.save(today_doc)
        store.save(yesterday_doc)

        # List by specific date
        result = store.list_by_group(group_guid, date=today)

        assert len(result) == 1
        assert result[0].guid == today_doc.guid

    def test_list_documents_by_date_range(self, tmp_path: Path) -> None:
        """Test listing documents in date range."""
        store = DocumentStore(tmp_path)
        group_guid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        now = datetime.now(UTC)

        # Create documents over several days
        dates = [now - timedelta(days=i) for i in range(5)]
        for i, date in enumerate(dates):
            doc = Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid=group_guid,
                title=f"Document {i}",
                content=f"Content {i}",
                created_at=date,
            )
            store.save(doc)

        # List date range (last 3 days)
        date_from = now - timedelta(days=2)
        date_to = now
        result = store.list_by_date_range(
            group_guid, date_from=date_from, date_to=date_to
        )

        assert len(result) == 3

    def test_count_documents(self, tmp_path: Path) -> None:
        """Test counting documents in a group."""
        store = DocumentStore(tmp_path)
        group_guid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        # Initially empty
        assert store.count_documents(group_guid) == 0

        # Add documents
        for i in range(7):
            doc = Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid=group_guid,
                title=f"Document {i}",
                content=f"Content {i}",
            )
            store.save(doc)

        assert store.count_documents(group_guid) == 7


class TestDocumentStoreEdgeCases:
    """Edge case tests for DocumentStore"""

    def test_unicode_content(self, tmp_path: Path) -> None:
        """Test storing and loading Unicode content."""
        store = DocumentStore(tmp_path)
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="日本語タイトル",
            content="中文内容 日本語コンテンツ 한국어 콘텐츠",
        )
        store.save(doc)

        loaded = store.load(doc.guid, doc.group_guid)

        assert loaded.title == "日本語タイトル"
        assert "中文内容" in loaded.content

    def test_document_with_all_fields(self, tmp_path: Path) -> None:
        """Test storing document with all fields populated."""
        store = DocumentStore(tmp_path)
        doc = Document(
            guid=str(uuid4()),
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Full Document",
            content="Complete content with all fields.",
            version=1,
            language="en",
            language_detected=True,
            word_count=5,
            metadata={
                "author": "Test",
                "tags": ["test", "complete"],
                "nested": {"key": "value"},
            },
        )
        store.save(doc)

        loaded = store.load(doc.guid, doc.group_guid)

        assert loaded.language == "en"
        assert loaded.language_detected is True
        assert loaded.metadata["nested"]["key"] == "value"

    def test_store_repr(self, tmp_path: Path) -> None:
        """Test store string representation."""
        store = DocumentStore(tmp_path)

        repr_str = repr(store)

        assert "DocumentStore" in repr_str
        assert str(tmp_path) in repr_str
