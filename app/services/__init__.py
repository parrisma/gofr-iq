"""Services package for gofr-iq.

This package contains all service layer modules:
- document_store: Canonical document storage
- source_registry: Source management
- language_detector: Language detection for documents
- duplicate_detector: Duplicate document detection
- ingest_service: Document ingestion orchestration
- query_service: Query orchestration
"""

from app.services.document_store import (
    DocumentNotFoundError,
    DocumentStore,
    DocumentStoreError,
)
from app.services.duplicate_detector import (
    CandidateDocument,
    DuplicateDetector,
    DuplicateResult,
    check_duplicate,
    compute_content_hash,
    cosine_similarity,
    normalize_text,
    tokenize,
)
from app.services.ingest_service import (
    IngestError,
    IngestResult,
    IngestService,
    IngestStatus,
    SourceValidationError,
    WordCountError,
    create_ingest_service,
)
from app.services.language_detector import (
    LanguageDetectionError,
    LanguageDetector,
    LanguageResult,
    detect_language,
    detect_language_with_confidence,
)
from app.services.source_registry import (
    SourceAccessDeniedError,
    SourceNotFoundError,
    SourceRegistry,
    SourceRegistryError,
)

__all__ = [
    "CandidateDocument",
    "DocumentNotFoundError",
    "DocumentStore",
    "DocumentStoreError",
    "DuplicateDetector",
    "DuplicateResult",
    "IngestError",
    "IngestResult",
    "IngestService",
    "IngestStatus",
    "LanguageDetectionError",
    "LanguageDetector",
    "LanguageResult",
    "SourceAccessDeniedError",
    "SourceNotFoundError",
    "SourceRegistry",
    "SourceRegistryError",
    "SourceValidationError",
    "WordCountError",
    "check_duplicate",
    "compute_content_hash",
    "cosine_similarity",
    "create_ingest_service",
    "detect_language",
    "detect_language_with_confidence",
    "normalize_text",
    "tokenize",
]
