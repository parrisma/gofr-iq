"""Tests for Basic Ingest Service - Phase 7.

Tests for document ingestion orchestration without external indexes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from app.models import DocumentCreate, Source, SourceType, TrustLevel
from app.services import (
    DocumentStore,
    DuplicateDetector,
    IngestResult,
    IngestService,
    IngestStatus,
    LanguageDetector,
    SourceRegistry,
    SourceValidationError,
    WordCountError,
    create_ingest_service,
)


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
    """Create ingest service."""
    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=language_detector,
        duplicate_detector=duplicate_detector,
    )


# =============================================================================
# BASIC INGEST TESTS
# =============================================================================


class TestIngestReturnsGuid:
    """Test that ingestion returns a valid GUID."""

    def test_ingest_returns_guid(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that ingest returns a valid GUID."""
        result = ingest_service.ingest(
            title="Test Document",
            content="This is test content for the document.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.guid is not None
        assert len(result.guid) >= 32  # UUID format

    def test_ingest_returns_success_status(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that successful ingest returns SUCCESS status."""
        result = ingest_service.ingest(
            title="Test Document",
            content="This is test content for the document.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.status == IngestStatus.SUCCESS
        assert result.is_success is True

    def test_ingest_result_has_created_at(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that result includes created_at timestamp."""
        result = ingest_service.ingest(
            title="Test Document",
            content="This is test content.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.created_at is not None
        assert isinstance(result.created_at, datetime)


# =============================================================================
# SOURCE VALIDATION TESTS
# =============================================================================


class TestIngestRejectsInvalidSource:
    """Test that ingestion rejects invalid sources."""

    def test_ingest_rejects_invalid_source(
        self,
        ingest_service: IngestService,
        group_guid: str,
    ) -> None:
        """Test that invalid source_guid raises SourceValidationError."""
        with pytest.raises(SourceValidationError) as exc_info:
            ingest_service.ingest(
                title="Test Document",
                content="This is test content.",
                source_guid=str(uuid.uuid4()),  # Non-existent source
                group_guid=group_guid,
            )

        assert "Source validation failed" in str(exc_info.value)

    def test_ingest_rejects_nonexistent_source(
        self,
        ingest_service: IngestService,
        group_guid: str,
    ) -> None:
        """Test that non-existent source raises error."""
        fake_source_guid = str(uuid.uuid4())

        with pytest.raises(SourceValidationError) as exc_info:
            ingest_service.ingest(
                title="Test",
                content="Content here.",
                source_guid=fake_source_guid,
                group_guid=group_guid,
            )

        assert fake_source_guid in str(exc_info.value)

    def test_ingest_accepts_any_source_for_any_group(
        self,
        ingest_service: IngestService,
        source_registry: SourceRegistry,
        document_store: DocumentStore,
        group_guid: str,
    ) -> None:
        """Any user can ingest documents with any source (sources are global)."""
        from uuid import uuid4
        
        # Create source (standalone)
        source = source_registry.create(
            name="Global Source",
            source_type=SourceType.NEWS_AGENCY,
        )

        # Ingest document with different group GUID (should succeed - sources are global)
        different_group_guid = str(uuid4())
        result = ingest_service.ingest(
            content="Test content",
            title="Test",
            source_guid=source.source_guid,
            group_guid=different_group_guid,  # Different from test's default group
        )

        assert result.status == IngestStatus.SUCCESS
        assert result.guid is not None


# =============================================================================
# WORD COUNT VALIDATION TESTS
# =============================================================================


class TestIngestRejectsLongDocument:
    """Test that ingestion rejects documents exceeding word limit."""

    def test_ingest_rejects_long_document(
        self,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that document exceeding word limit raises WordCountError."""
        # Create service with low word limit for testing
        service = IngestService(
            document_store=document_store,
            source_registry=source_registry,
            language_detector=LanguageDetector(),
            duplicate_detector=DuplicateDetector(),
            max_word_count=100,
        )

        long_content = " ".join(["word"] * 200)  # 200 words

        with pytest.raises(WordCountError) as exc_info:
            service.ingest(
                title="Long Document",
                content=long_content,
                source_guid=source.source_guid,
                group_guid=group_guid,
            )

        assert exc_info.value.word_count == 200
        assert exc_info.value.max_count == 100

    def test_ingest_accepts_document_at_limit(
        self,
        document_store: DocumentStore,
        source_registry: SourceRegistry,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that document at word limit is accepted."""
        service = IngestService(
            document_store=document_store,
            source_registry=source_registry,
            language_detector=LanguageDetector(),
            duplicate_detector=DuplicateDetector(),
            max_word_count=100,
        )

        content = " ".join(["word"] * 100)  # Exactly 100 words

        result = service.ingest(
            title="At Limit",
            content=content,
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.status == IngestStatus.SUCCESS
        assert result.word_count == 100


# =============================================================================
# LANGUAGE DETECTION TESTS
# =============================================================================


class TestIngestSetsLanguage:
    """Test that ingestion correctly sets language."""

    def test_ingest_uses_provided_language(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that provided language is used."""
        result = ingest_service.ingest(
            title="Test Document",
            content="This is test content.",
            source_guid=source.source_guid,
            group_guid=group_guid,
            language="zh",
        )

        assert result.language == "zh"
        assert result.language_detected is False

    def test_ingest_detects_english(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that English is auto-detected."""
        result = ingest_service.ingest(
            title="Breaking News Today",
            content="The stock market showed strong gains today with major indices rising.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.language == "en"
        assert result.language_detected is True

    def test_ingest_detects_chinese(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that Chinese is auto-detected."""
        result = ingest_service.ingest(
            title="市场新闻",
            content="今日股市大涨，主要指数上涨百分之二。",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.language in ["zh", "ko"]  # langdetect may vary
        assert result.language_detected is True

    def test_ingest_detects_japanese(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that Japanese is auto-detected."""
        result = ingest_service.ingest(
            title="市場ニュース",
            content="今日の株式市場は大幅に上昇しました。",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.language == "ja"
        assert result.language_detected is True


# =============================================================================
# DUPLICATE DETECTION TESTS
# =============================================================================


class TestIngestFlagsDuplicate:
    """Test that ingestion flags duplicate documents."""

    def test_ingest_flags_exact_duplicate(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that exact duplicate is flagged."""
        # Ingest first document
        result1 = ingest_service.ingest(
            title="Original Document",
            content="This is the original content for testing.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )
        assert result1.status == IngestStatus.SUCCESS

        # Ingest duplicate
        result2 = ingest_service.ingest(
            title="Original Document",
            content="This is the original content for testing.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result2.status == IngestStatus.DUPLICATE
        assert result2.is_duplicate is True
        assert result2.duplicate_of == result1.guid
        assert result2.duplicate_score == 1.0

    def test_duplicate_still_stored(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that duplicates are still stored (append-only)."""
        # Ingest first document
        result1 = ingest_service.ingest(
            title="Original",
            content="Original content here.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        # Ingest duplicate
        result2 = ingest_service.ingest(
            title="Original",
            content="Original content here.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        # Both should have different GUIDs
        assert result1.guid != result2.guid

        # Both should be retrievable
        doc1 = ingest_service.get_document(result1.guid, group_guid)
        doc2 = ingest_service.get_document(result2.guid, group_guid)

        assert doc1 is not None
        assert doc2 is not None

    def test_different_content_not_duplicate(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that different content is not flagged as duplicate."""
        result1 = ingest_service.ingest(
            title="Document A",
            content="Content for document A about topic one.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        result2 = ingest_service.ingest(
            title="Document B",
            content="Completely different content about topic two.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result1.status == IngestStatus.SUCCESS
        assert result2.status == IngestStatus.SUCCESS
        assert result2.duplicate_of is None


# =============================================================================
# FILE STORAGE TESTS
# =============================================================================


class TestIngestCreatesFile:
    """Test that ingestion creates files on disk."""

    def test_ingest_creates_file(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that ingestion creates a file on disk."""
        result = ingest_service.ingest(
            title="Stored Document",
            content="Content that should be stored to disk.",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        # Should be retrievable
        doc = ingest_service.get_document(result.guid, group_guid)

        assert doc is not None
        assert doc.guid == result.guid
        assert doc.title == "Stored Document"

    def test_ingest_stores_all_fields(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that all fields are stored correctly."""
        result = ingest_service.ingest(
            title="Full Document",
            content="Full content here with all fields.",
            source_guid=source.source_guid,
            group_guid=group_guid,
            language="en",
            metadata={"author": "Test Author", "category": "Testing"},
        )

        doc = ingest_service.get_document(result.guid, group_guid)

        assert doc is not None
        assert doc.title == "Full Document"
        assert doc.content == "Full content here with all fields."
        assert doc.source_guid == source.source_guid
        assert doc.group_guid == group_guid
        assert doc.language == "en"
        assert doc.metadata["author"] == "Test Author"

    def test_ingest_sets_word_count(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that word count is calculated and stored."""
        result = ingest_service.ingest(
            title="Word Count Test",
            content="One two three four five",
            source_guid=source.source_guid,
            group_guid=group_guid,
        )

        assert result.word_count == 5

        doc = ingest_service.get_document(result.guid, group_guid)
        assert doc is not None
        assert doc.word_count == 5


# =============================================================================
# INGEST RESULT TESTS
# =============================================================================


class TestIngestResult:
    """Tests for IngestResult dataclass."""

    def test_ingest_result_to_dict(self) -> None:
        """Test IngestResult.to_dict()."""
        result = IngestResult(
            guid="test-guid-123",
            status=IngestStatus.SUCCESS,
            language="en",
            language_detected=True,
            word_count=100,
        )

        d = result.to_dict()

        assert d["guid"] == "test-guid-123"
        assert d["status"] == "success"
        assert d["language"] == "en"
        assert d["language_detected"] is True
        assert d["word_count"] == 100

    def test_ingest_result_duplicate_to_dict(self) -> None:
        """Test IngestResult.to_dict() for duplicate."""
        result = IngestResult(
            guid="dup-guid",
            status=IngestStatus.DUPLICATE,
            language="zh",
            language_detected=False,
            duplicate_of="original-guid",
            duplicate_score=0.98,
            word_count=50,
        )

        d = result.to_dict()

        assert d["status"] == "duplicate"
        assert d["duplicate_of"] == "original-guid"
        assert d["duplicate_score"] == 0.98

    def test_ingest_result_failed_to_dict(self) -> None:
        """Test IngestResult.to_dict() for failed."""
        result = IngestResult(
            guid="failed-guid",
            status=IngestStatus.FAILED,
            error="Source not found",
        )

        d = result.to_dict()

        assert d["status"] == "failed"
        assert d["error"] == "Source not found"


# =============================================================================
# BATCH INGEST TESTS
# =============================================================================


class TestIngestBatch:
    """Tests for batch ingestion."""

    def test_ingest_batch_success(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test successful batch ingestion."""
        inputs = [
            DocumentCreate(
                title="Doc 1",
                content="Content for doc 1.",
                source_guid=source.source_guid,
                group_guid=group_guid,
            ),
            DocumentCreate(
                title="Doc 2",
                content="Content for doc 2.",
                source_guid=source.source_guid,
                group_guid=group_guid,
            ),
        ]

        results = ingest_service.ingest_batch(inputs)

        assert len(results) == 2
        assert all(r.status == IngestStatus.SUCCESS for r in results)

    def test_ingest_batch_continues_on_error(
        self,
        ingest_service: IngestService,
        source: Source,
        group_guid: str,
    ) -> None:
        """Test that batch continues on error by default."""
        inputs = [
            DocumentCreate(
                title="Good Doc",
                content="Valid content.",
                source_guid=source.source_guid,
                group_guid=group_guid,
            ),
            DocumentCreate(
                title="Bad Doc",
                content="Content.",
                source_guid=str(uuid.uuid4()),  # Invalid source
                group_guid=group_guid,
            ),
            DocumentCreate(
                title="Another Good",
                content="More valid content.",
                source_guid=source.source_guid,
                group_guid=group_guid,
            ),
        ]

        results = ingest_service.ingest_batch(inputs)

        assert len(results) == 3
        assert results[0].status == IngestStatus.SUCCESS
        assert results[1].status == IngestStatus.FAILED
        assert results[2].status == IngestStatus.SUCCESS


# =============================================================================
# FACTORY FUNCTION TESTS
# =============================================================================


class TestCreateIngestService:
    """Tests for create_ingest_service factory."""

    def test_create_ingest_service(self, storage_path: Path) -> None:
        """Test factory creates working service."""
        service = create_ingest_service(storage_path)

        assert isinstance(service, IngestService)
        assert service.max_word_count == 20_000

    def test_create_ingest_service_custom_word_count(
        self, storage_path: Path
    ) -> None:
        """Test factory with custom word count."""
        service = create_ingest_service(storage_path, max_word_count=10_000)

        assert service.max_word_count == 10_000


# =============================================================================
# SERVICE REPR TEST
# =============================================================================


class TestIngestServiceRepr:
    """Tests for IngestService string representation."""

    def test_repr(self, ingest_service: IngestService) -> None:
        """Test __repr__ method."""
        repr_str = repr(ingest_service)

        assert "IngestService" in repr_str
        assert "max_words=" in repr_str
        assert "duplicates=" in repr_str
