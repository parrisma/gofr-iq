"""Services package for gofr-iq.

This package contains all service layer modules:
- document_store: Canonical document storage
- source_registry: Source management
- ingest_service: Document ingestion orchestration
- query_service: Query orchestration
"""

from app.services.document_store import (
    DocumentNotFoundError,
    DocumentStore,
    DocumentStoreError,
)

__all__ = [
    "DocumentNotFoundError",
    "DocumentStore",
    "DocumentStoreError",
]
