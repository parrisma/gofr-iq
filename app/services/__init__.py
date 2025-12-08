"""Services package for gofr-iq.

This package contains all service layer modules:
- document_store: Canonical document storage
- source_registry: Source management
- language_detector: Language detection for documents
- duplicate_detector: Duplicate document detection
- ingest_service: Document ingestion orchestration
- audit_service: Audit logging for all operations
- query_service: Query orchestration
"""

from app.services.audit_service import (
    AuditEntry,
    AuditEventType,
    AuditService,
    create_audit_service,
    log_document_ingest,
    log_document_query,
    log_document_retrieve,
    log_source_create,
    log_source_delete,
    log_source_update,
)
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
from app.services.embedding_index import (
    Chunk,
    ChunkConfig,
    DeterministicEmbeddingFunction,
    EmbeddingIndex,
    SimilarityResult,
    create_embedding_index,
)
from app.services.graph_index import (
    GraphIndex,
    GraphNode,
    GraphRelationship,
    NodeLabel,
    RelationType,
    TraversalResult,
    create_graph_index,
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
from app.services.query_service import (
    QueryFilters,
    QueryResponse,
    QueryResult,
    QueryService,
    ScoringWeights,
    create_query_service,
)
from app.services.source_registry import (
    SourceAccessDeniedError,
    SourceNotFoundError,
    SourceRegistry,
    SourceRegistryError,
)

__all__ = [
    "AuditEntry",
    "AuditEventType",
    "AuditService",
    "CandidateDocument",
    "Chunk",
    "ChunkConfig",
    "DocumentNotFoundError",
    "DocumentStore",
    "DocumentStoreError",
    "DuplicateDetector",
    "DuplicateResult",
    "EmbeddingIndex",
    "GraphIndex",
    "GraphNode",
    "GraphRelationship",
    "IngestError",
    "IngestResult",
    "IngestService",
    "IngestStatus",
    "LanguageDetectionError",
    "LanguageDetector",
    "LanguageResult",
    "NodeLabel",
    "QueryFilters",
    "QueryResponse",
    "QueryResult",
    "QueryService",
    "RelationType",
    "ScoringWeights",
    "SimilarityResult",
    "SourceAccessDeniedError",
    "SourceNotFoundError",
    "SourceRegistry",
    "SourceRegistryError",
    "SourceValidationError",
    "TraversalResult",
    "WordCountError",
    "check_duplicate",
    "compute_content_hash",
    "cosine_similarity",
    "create_audit_service",
    "create_embedding_index",
    "create_graph_index",
    "create_ingest_service",
    "create_query_service",
    "detect_language",
    "detect_language_with_confidence",
    "DeterministicEmbeddingFunction",
    "log_document_ingest",
    "log_document_query",
    "log_document_retrieve",
    "log_source_create",
    "log_source_delete",
    "log_source_update",
    "normalize_text",
    "tokenize",
]
