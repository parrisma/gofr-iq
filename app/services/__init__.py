"""Services package for gofr-iq.

This package contains all service layer modules:
- document_store: Canonical document storage
- source_registry: Source management
- language_detector: Language detection for documents
- ingest_service: Document ingestion orchestration
- query_service: Query orchestration
"""

from app.services.document_store import (
    DocumentNotFoundError,
    DocumentStore,
    DocumentStoreError,
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
    "DocumentNotFoundError",
    "DocumentStore",
    "DocumentStoreError",
    "LanguageDetectionError",
    "LanguageDetector",
    "LanguageResult",
    "detect_language",
    "detect_language_with_confidence",
    "SourceAccessDeniedError",
    "SourceNotFoundError",
    "SourceRegistry",
    "SourceRegistryError",
]
