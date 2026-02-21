"""Pydantic models for gofr-iq.

This package contains all data models used in the APAC Brokerage News Repository.
Models are organized by domain:

- group: Group and token permission models
- source: News source models
- document: Document and versioning models  
- query: Query request/response models
"""

from .document import (
    MAX_WORD_COUNT,
    Document,
    DocumentCreate,
    DocumentUpdate,
    count_words,
    validate_word_count,
)
from .group import Group, GroupMetadata, Permission, TokenPermissions, PUBLIC_GROUP
from .query import (
    DocumentResult,
    GraphQueryRequest,
    GraphQueryResponse,
    QueryFilters,
    QueryRequest,
    QueryResponse,
    RelatedEntity,
    ScoringWeights,
    SimilarityMode,
)
from .source import Source, SourceMetadata, SourceType, TrustLevel
from .client_profile import ClientProfile

__all__ = [
    # Document models
    "Document",
    "DocumentCreate",
    "DocumentUpdate",
    "MAX_WORD_COUNT",
    "count_words",
    "validate_word_count",
    # Group models
    "Group",
    "GroupMetadata",
    "Permission",
    "TokenPermissions",
    "PUBLIC_GROUP",
    # Query models
    "DocumentResult",
    "GraphQueryRequest",
    "GraphQueryResponse",
    "QueryFilters",
    "QueryRequest",
    "QueryResponse",
    "RelatedEntity",
    "ScoringWeights",
    "SimilarityMode",
    # Source models
    "Source",
    "SourceMetadata",
    "SourceType",
    "TrustLevel",
    # Client models
    "ClientProfile",
]
