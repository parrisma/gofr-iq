"""Basic Ingest Service - Phase 7.

Orchestrates document ingestion without external indexes.
Validates source, word count, detects language, checks duplicates,
and stores documents to the canonical file store.

Full ingest flow (Phase 7 - file-only):
1. Validate source_guid exists
2. Validate word count (max 20,000)
3. Generate document GUID (UUID v4)
4. Detect language (auto-detect if not provided)
5. Check for duplicates
6. Store to canonical file store
7. Return { guid, status, duplicate_of?, language }

External indexing (Elasticsearch, ChromaDB, Neo4j) will be added in later phases.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.models import Document, DocumentCreate, count_words
from app.services.document_store import DocumentNotFoundError, DocumentStore
from app.services.duplicate_detector import DuplicateDetector, DuplicateResult
from app.services.embedding_index import EmbeddingIndex
from app.services.graph_index import GraphIndex, NodeLabel
from app.services.language_detector import LanguageDetector, LanguageResult
from app.services.source_registry import SourceNotFoundError, SourceRegistry

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "IngestError",
    "IngestResult",
    "IngestService",
    "IngestStatus",
    "SourceValidationError",
    "WordCountError",
]


# =============================================================================
# EXCEPTIONS
# =============================================================================


class IngestError(Exception):
    """Base exception for ingest errors."""

    pass


class SourceValidationError(IngestError):
    """Error validating source during ingestion."""

    def __init__(self, source_guid: str, message: str = "Source not found") -> None:
        self.source_guid = source_guid
        super().__init__(f"Source validation failed for '{source_guid}': {message}")


class WordCountError(IngestError):
    """Error when document exceeds word count limit."""

    def __init__(self, word_count: int, max_count: int = 20_000) -> None:
        self.word_count = word_count
        self.max_count = max_count
        super().__init__(
            f"Document exceeds word count limit: {word_count} > {max_count}"
        )


# =============================================================================
# DATA CLASSES
# =============================================================================


class IngestStatus(str, Enum):
    """Status of document ingestion."""

    SUCCESS = "success"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass
class IngestResult:
    """Result of document ingestion.

    Attributes:
        guid: Document GUID (UUID v4)
        status: Ingestion status (success, duplicate, failed)
        language: Detected or provided language
        language_detected: Whether language was auto-detected
        duplicate_of: Original document GUID if duplicate
        duplicate_score: Similarity score if duplicate
        word_count: Number of words in content
        error: Error message if failed
        created_at: Timestamp when document was created
    """

    guid: str
    status: IngestStatus
    language: str = "en"
    language_detected: bool = False
    duplicate_of: str | None = None
    duplicate_score: float | None = None
    word_count: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_success(self) -> bool:
        """Check if ingestion was successful."""
        return self.status == IngestStatus.SUCCESS

    @property
    def is_duplicate(self) -> bool:
        """Check if document was flagged as duplicate."""
        return self.status == IngestStatus.DUPLICATE

    @property
    def is_failed(self) -> bool:
        """Check if ingestion failed."""
        return self.status == IngestStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "guid": self.guid,
            "status": self.status.value,
            "language": self.language,
            "language_detected": self.language_detected,
            "word_count": self.word_count,
            "created_at": self.created_at.isoformat(),
        }
        if self.duplicate_of:
            result["duplicate_of"] = self.duplicate_of
        if self.duplicate_score is not None:
            result["duplicate_score"] = self.duplicate_score
        if self.error:
            result["error"] = self.error
        return result


# =============================================================================
# INGEST SERVICE
# =============================================================================


@dataclass
class IngestService:
    """Service for ingesting documents into the repository.

    Orchestrates the full ingestion flow:
    1. Validate source exists
    2. Validate word count
    3. Generate document GUID
    4. Detect language
    5. Check duplicates
    6. Store to file

    Attributes:
        document_store: Storage for documents
        source_registry: Registry for source validation
        language_detector: Language detection service
        duplicate_detector: Duplicate detection service
        max_word_count: Maximum allowed word count (default 20,000)
    """

    document_store: DocumentStore
    source_registry: SourceRegistry
    language_detector: LanguageDetector = field(default_factory=LanguageDetector)
    duplicate_detector: DuplicateDetector = field(default_factory=DuplicateDetector)
    embedding_index: EmbeddingIndex | None = None
    graph_index: GraphIndex | None = None
    max_word_count: int = 20_000

    def ingest(
        self,
        title: str,
        content: str,
        source_guid: str,
        group_guid: str,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestResult:
        """Ingest a document into the repository.

        Args:
            title: Document title
            content: Document content
            source_guid: GUID of the source
            group_guid: GUID of the group this document belongs to
            language: Language code (auto-detected if not provided)
            metadata: Optional metadata dictionary

        Returns:
            IngestResult with document details

        Raises:
            SourceValidationError: If source_guid is invalid
            WordCountError: If content exceeds word count limit
        """
        # Import APAC_LANGUAGES at module level
        from app.services.language_detector import APAC_LANGUAGES

        # Step 1: Generate document GUID first (so we can return it on error)
        doc_guid = str(uuid.uuid4())

        # Step 2: Validate source exists and belongs to the specified group
        try:
            source = self.source_registry.get(source_guid, access_groups=[group_guid])
            if source is None:
                raise SourceValidationError(source_guid)
        except SourceNotFoundError:
            raise SourceValidationError(source_guid)

        # Step 3: Validate word count
        word_count = count_words(content)
        if word_count > self.max_word_count:
            raise WordCountError(word_count, self.max_word_count)

        # Step 4: Detect language
        lang_result: LanguageResult
        language_detected = False
        if language:
            # Use provided language
            lang_result = LanguageResult(
                language=language,
                confidence=1.0,
                detected_code=language,
                is_apac=language in APAC_LANGUAGES,
            )
        else:
            # Auto-detect language
            lang_result = self.language_detector.detect(f"{title} {content}")
            language_detected = True

        # Step 5: Check for duplicates
        dup_result: DuplicateResult = self.duplicate_detector.check(title, content)

        # Step 6: Create document model
        doc = Document(
            guid=doc_guid,
            source_guid=source_guid,
            group_guid=group_guid,
            title=title,
            content=content,
            language=lang_result.language,
            language_detected=language_detected,
            word_count=word_count,
            version=1,
            duplicate_of=dup_result.duplicate_of,
            duplicate_score=dup_result.score if dup_result.is_duplicate else 0.0,
            metadata=metadata or {},
        )

        # Step 7: Store to file
        self.document_store.save(doc)

        # Step 8 & 9: Indexing with Rollback
        try:
            # Step 8: Index in ChromaDB (if configured)
            if self.embedding_index:
                self.embedding_index.embed_document(
                    document_guid=doc.guid,
                    content=doc.content,
                    group_guid=doc.group_guid,
                    source_guid=doc.source_guid,
                    language=doc.language,
                    metadata=doc.metadata,
                )

            # Step 9: Index in Neo4j (if configured)
            if self.graph_index:
                self.graph_index.create_document_node(
                    document_guid=doc.guid,
                    source_guid=doc.source_guid,
                    group_guid=doc.group_guid,
                    title=doc.title,
                    language=doc.language,
                    created_at=doc.created_at,
                    metadata=doc.metadata,
                )

        except Exception as e:
            # Rollback on failure
            print(f"Error indexing document {doc.guid}: {e}. Rolling back.")

            # 1. Remove from file store
            try:
                self.document_store.delete(doc.guid, doc.group_guid, doc.created_at)
            except Exception as rollback_error:
                print(f"CRITICAL: Failed to rollback file store for {doc.guid}: {rollback_error}")

            # 2. Remove from embedding index
            if self.embedding_index:
                try:
                    self.embedding_index.delete_document(doc.guid)
                except Exception as rollback_error:
                    print(f"CRITICAL: Failed to rollback embedding index for {doc.guid}: {rollback_error}")

            # 3. Remove from graph index
            if self.graph_index:
                try:
                    self.graph_index.delete_node(NodeLabel.DOCUMENT, doc.guid)
                except Exception as rollback_error:
                    print(f"CRITICAL: Failed to rollback graph index for {doc.guid}: {rollback_error}")

            return IngestResult(
                guid=doc_guid,
                status=IngestStatus.FAILED,
                language=lang_result.language,
                language_detected=language_detected,
                word_count=word_count,
                error=f"Indexing failed: {str(e)}",
                created_at=doc.created_at,
            )

        # Step 10: Register with duplicate detector for future checks
        self.duplicate_detector.register(doc_guid, title, content)

        # Determine status
        status = IngestStatus.DUPLICATE if dup_result.is_duplicate else IngestStatus.SUCCESS

        return IngestResult(
            guid=doc_guid,
            status=status,
            language=lang_result.language,
            language_detected=language_detected,
            duplicate_of=dup_result.duplicate_of,
            duplicate_score=dup_result.score if dup_result.is_duplicate else None,
            word_count=word_count,
            created_at=doc.created_at,
        )

    def ingest_from_input(
        self,
        input_data: DocumentCreate,
    ) -> IngestResult:
        """Ingest a document from a DocumentCreate input model.

        Args:
            input_data: Document creation input (contains group_guid)

        Returns:
            IngestResult with document details
        """
        return self.ingest(
            title=input_data.title,
            content=input_data.content,
            source_guid=input_data.source_guid,
            group_guid=input_data.group_guid,
            language=input_data.language,
            metadata=input_data.metadata,
        )

    def ingest_batch(
        self,
        documents: Sequence[DocumentCreate],
        stop_on_error: bool = False,
    ) -> list[IngestResult]:
        """Ingest multiple documents.

        Args:
            documents: Sequence of DocumentCreate inputs
            stop_on_error: Stop on first error (default False)

        Returns:
            List of IngestResult for each document
        """
        results: list[IngestResult] = []

        for doc_input in documents:
            try:
                result = self.ingest_from_input(doc_input)
                results.append(result)
            except IngestError as e:
                error_result = IngestResult(
                    guid=str(uuid.uuid4()),
                    status=IngestStatus.FAILED,
                    error=str(e),
                )
                results.append(error_result)
                if stop_on_error:
                    break

        return results

    def get_document(self, guid: str, group_guid: str) -> Document | None:
        """Retrieve a document by GUID.

        Args:
            guid: Document GUID
            group_guid: Group GUID for lookup

        Returns:
            Document if found, None otherwise
        """
        try:
            return self.document_store.load(guid, group_guid=group_guid)
        except DocumentNotFoundError:
            return None

    def load_existing_documents(self, group_guid: str) -> int:
        """Load existing documents into duplicate detector.

        Call this on startup to populate the duplicate detector
        with previously ingested documents.

        Args:
            group_guid: Group GUID to load documents from

        Returns:
            Number of documents loaded
        """
        documents = self.document_store.list_by_group(group_guid=group_guid)
        return self.duplicate_detector.load_documents(documents)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"IngestService("
            f"max_words={self.max_word_count}, "
            f"duplicates={self.duplicate_detector.document_count})"
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


def create_ingest_service(
    storage_path: str | Path,
    max_word_count: int = 20_000,
    embedding_index: EmbeddingIndex | None = None,
    graph_index: GraphIndex | None = None,
) -> IngestService:
    """Create an IngestService with standard configuration.

    Args:
        storage_path: Path to storage directory
        max_word_count: Maximum word count (default 20,000)
        embedding_index: Optional embedding index
        graph_index: Optional graph index

    Returns:
        Configured IngestService
    """
    storage_path = Path(storage_path)

    document_store = DocumentStore(base_path=storage_path / "documents")
    source_registry = SourceRegistry(base_path=storage_path / "sources")
    language_detector = LanguageDetector()
    duplicate_detector = DuplicateDetector()

    return IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=language_detector,
        duplicate_detector=duplicate_detector,
        embedding_index=embedding_index,
        graph_index=graph_index,
        max_word_count=max_word_count,
    )
