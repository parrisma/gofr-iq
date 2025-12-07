"""Query request and response models for APAC Brokerage News Repository.

These models define the query interface for hybrid search including:
- Semantic, keyword, and graph-based similarity search
- Filtering by date, region, sector, company, source, language
- Scoring weight configuration
- Recency and trust level boosting
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class SimilarityMode(str, Enum):
    """Search similarity mode."""

    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class QueryFilters(BaseModel):
    """Filters for query results.

    All filters are optional and applied as AND conditions.
    """

    date_from: datetime | None = Field(default=None, description="Filter from date")
    date_to: datetime | None = Field(default=None, description="Filter to date")
    regions: list[str] | None = Field(default=None, description="Filter by regions")
    sectors: list[str] | None = Field(default=None, description="Filter by sectors")
    companies: list[str] | None = Field(
        default=None, description="Filter by company tickers"
    )
    sources: list[str] | None = Field(default=None, description="Filter by source GUIDs")
    languages: list[str] | None = Field(
        default=None, description="Filter by language codes"
    )

    @field_validator("regions", "sectors", "companies", "languages")
    @classmethod
    def normalize_list_values(cls, v: list[str] | None) -> list[str] | None:
        """Normalize list values to lowercase."""
        if v is None:
            return None
        return [item.lower().strip() for item in v if item]

    @model_validator(mode="after")
    def validate_date_range(self) -> "QueryFilters":
        """Validate date range if both dates are provided."""
        if self.date_from and self.date_to:
            if self.date_from > self.date_to:
                raise ValueError("date_from must be before date_to")
        return self

    @property
    def has_filters(self) -> bool:
        """Check if any filters are set."""
        return any(
            [
                self.date_from,
                self.date_to,
                self.regions,
                self.sectors,
                self.companies,
                self.sources,
                self.languages,
            ]
        )


class ScoringWeights(BaseModel):
    """Weights for hybrid scoring components.

    Weights should sum to 1.0 for normalized scoring.
    """

    semantic: float = Field(default=0.5, ge=0.0, le=1.0, description="Semantic weight")
    keyword: float = Field(default=0.3, ge=0.0, le=1.0, description="Keyword weight")
    graph: float = Field(default=0.2, ge=0.0, le=1.0, description="Graph weight")

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "ScoringWeights":
        """Validate that weights sum to approximately 1.0."""
        total = self.semantic + self.keyword + self.graph
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        return self


class QueryRequest(BaseModel):
    """Request model for document queries.

    Attributes:
        query_text: Search text (natural language query)
        nearest_k: Number of results to return
        filters: Optional query filters
        similarity_mode: Type of similarity search
        scoring_weights: Weights for hybrid scoring
        include_duplicates: Whether to include duplicate documents
        boost_recency: Apply recency boost to recent documents
        horizon_days: Days for recency horizon (default 30)
    """

    query_text: str = Field(..., min_length=1, max_length=5000, description="Search text")
    nearest_k: int = Field(default=10, ge=1, le=100, description="Number of results")
    filters: QueryFilters | None = Field(default=None)
    similarity_mode: SimilarityMode = Field(default=SimilarityMode.HYBRID)
    scoring_weights: ScoringWeights | None = Field(default=None)
    include_duplicates: bool = Field(default=False)
    boost_recency: bool = Field(default=True)
    horizon_days: int = Field(
        default=30, ge=1, le=365, description="Recency horizon in days"
    )

    @field_validator("query_text")
    @classmethod
    def validate_query_text(cls, v: str) -> str:
        """Validate and normalize query text."""
        return v.strip()

    @property
    def effective_weights(self) -> ScoringWeights:
        """Get effective scoring weights (defaults if not provided)."""
        return self.scoring_weights or ScoringWeights()


class DocumentResult(BaseModel):
    """Single document result from a query.

    Includes the document metadata and scoring breakdown.
    """

    guid: str = Field(..., description="Document GUID")
    title: str = Field(..., description="Document title")
    source_guid: str = Field(..., description="Source GUID")
    source_name: str | None = Field(default=None, description="Source name")
    group_guid: str = Field(..., description="Group GUID")
    language: str = Field(..., description="Document language")
    created_at: datetime = Field(..., description="Document creation time")
    word_count: int = Field(default=0, description="Document word count")
    snippet: str | None = Field(default=None, description="Content snippet")
    score: float = Field(..., ge=0.0, description="Final score")
    score_breakdown: dict[str, float] = Field(
        default_factory=dict, description="Score components"
    )
    is_duplicate: bool = Field(default=False)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    """Response model for document queries.

    Attributes:
        query_id: Unique identifier for this query
        query_text: The original query text
        results: List of document results
        total_found: Total number of matching documents
        filters_applied: Filters that were applied
        similarity_mode: Similarity mode used
        scoring_weights: Scoring weights used
        took_ms: Query execution time in milliseconds
        created_at: Response timestamp
    """

    query_id: str = Field(default_factory=lambda: str(uuid4()))
    query_text: str = Field(..., description="Original query")
    results: list[DocumentResult] = Field(default_factory=list)
    total_found: int = Field(default=0, ge=0, description="Total matches")
    filters_applied: QueryFilters | None = Field(default=None)
    similarity_mode: SimilarityMode = Field(default=SimilarityMode.HYBRID)
    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)
    took_ms: float = Field(default=0.0, ge=0.0, description="Query time in ms")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def count(self) -> int:
        """Number of results returned."""
        return len(self.results)

    @property
    def has_more(self) -> bool:
        """Check if there are more results beyond those returned."""
        return self.total_found > self.count

    def to_summary(self) -> dict[str, Any]:
        """Generate a summary of the query response."""
        return {
            "query_id": self.query_id,
            "query_text": self.query_text[:100] + "..." if len(self.query_text) > 100 else self.query_text,
            "results_returned": self.count,
            "total_found": self.total_found,
            "took_ms": self.took_ms,
            "similarity_mode": self.similarity_mode.value,
        }


class RelatedEntity(BaseModel):
    """Related entity from graph traversal.

    Used for company, sector, and region relationships.
    """

    entity_type: str = Field(..., description="Entity type (company, sector, region)")
    entity_id: str = Field(..., description="Entity identifier")
    entity_name: str = Field(..., description="Entity name")
    relationship: str = Field(..., description="Relationship type")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)


class GraphQueryRequest(BaseModel):
    """Request for graph-based queries.

    Used for entity relationship traversal.
    """

    entity_type: str = Field(..., description="Starting entity type")
    entity_id: str = Field(..., description="Starting entity ID")
    relationship_types: list[str] | None = Field(
        default=None, description="Relationship types to follow"
    )
    max_depth: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=20, ge=1, le=100)


class GraphQueryResponse(BaseModel):
    """Response for graph queries."""

    query_id: str = Field(default_factory=lambda: str(uuid4()))
    starting_entity: RelatedEntity = Field(...)
    related_entities: list[RelatedEntity] = Field(default_factory=list)
    documents: list[DocumentResult] = Field(default_factory=list)
    took_ms: float = Field(default=0.0, ge=0.0)
