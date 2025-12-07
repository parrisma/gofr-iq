"""Source models for news sources.

Sources represent the origin of news documents - news agencies, internal
research, etc. Each source belongs to exactly one group and has a trust
level that affects scoring in search results.

Schema from IMPLEMENTATION.md Section 3.2.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator


class TrustLevel(str, Enum):
    """Trust level for source credibility scoring.
    
    Higher trust sources receive a boost in query results:
    - high: 1.2x boost (established, verified sources)
    - medium: 1.0x (standard sources)
    - low: 0.8x (less verified sources)
    - unverified: 0.6x (new or unverified sources)
    """
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNVERIFIED = "unverified"
    
    @property
    def boost_factor(self) -> float:
        """Get the scoring boost factor for this trust level."""
        factors = {
            TrustLevel.HIGH: 1.2,
            TrustLevel.MEDIUM: 1.0,
            TrustLevel.LOW: 0.8,
            TrustLevel.UNVERIFIED: 0.6,
        }
        return factors[self]


class SourceType(str, Enum):
    """Type of news source."""
    NEWS_AGENCY = "news_agency"
    INTERNAL = "internal"
    RESEARCH = "research"
    GOVERNMENT = "government"
    CORPORATE = "corporate"
    SOCIAL = "social"
    OTHER = "other"


class SourceMetadata(BaseModel):
    """Optional metadata for a source.
    
    Attributes:
        feed_url: URL for automated feed ingestion
        update_frequency: How often the source is updated
        department: For internal sources, the originating department
        Additional fields can be added as needed.
    """
    feed_url: str | None = None
    update_frequency: str | None = None
    department: str | None = None
    
    model_config = {"extra": "allow"}


class Source(BaseModel):
    """Source model representing a news or document source.
    
    Sources track where documents come from and provide trust scoring.
    Each source belongs to exactly one group. Tokens with appropriate
    permissions on that group can perform CRUD operations.
    
    Attributes:
        source_guid: Unique identifier for the source (UUID format)
        group_guid: The group this source belongs to
        name: Human-readable source name
        type: Type of source (news_agency, internal, etc.)
        region: Geographic region coverage
        languages: Languages this source provides
        trust_level: Credibility level affecting search scoring
        created_at: When the source was created
        updated_at: When the source was last updated
        active: Whether the source is active (soft delete support)
        metadata: Optional additional source metadata
    
    Example:
        >>> source = Source(
        ...     source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
        ...     group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        ...     name="Reuters APAC",
        ...     type=SourceType.NEWS_AGENCY,
        ...     region="APAC",
        ...     languages=["en", "zh", "ja"],
        ...     trust_level=TrustLevel.HIGH,
        ... )
    """
    source_guid: Annotated[str, Field(
        min_length=36,
        max_length=36,
        pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
        description="UUID format source identifier",
    )]
    group_guid: Annotated[str, Field(
        min_length=36,
        max_length=36,
        pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
        description="UUID of the owning group",
    )]
    name: Annotated[str, Field(
        min_length=1,
        max_length=255,
        description="Human-readable source name",
    )]
    type: SourceType = Field(
        default=SourceType.OTHER,
        description="Type of source",
    )
    region: str | None = Field(
        default=None,
        max_length=100,
        description="Geographic region coverage",
    )
    languages: list[str] = Field(
        default_factory=lambda: ["en"],
        description="Languages this source provides (ISO 639-1 codes)",
    )
    trust_level: TrustLevel = Field(
        default=TrustLevel.UNVERIFIED,
        description="Credibility level affecting search scoring",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the source was created",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the source was last updated",
    )
    active: bool = Field(
        default=True,
        description="Whether the source is active",
    )
    metadata: SourceMetadata | None = Field(
        default=None,
        description="Optional additional metadata",
    )
    
    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, v: Any) -> SourceType:
        """Convert string type to SourceType enum."""
        if isinstance(v, str):
            return SourceType(v)
        return v
    
    @field_validator("trust_level", mode="before")
    @classmethod
    def validate_trust_level(cls, v: Any) -> TrustLevel:
        """Convert string trust level to TrustLevel enum."""
        if isinstance(v, str):
            return TrustLevel(v)
        return v
    
    @field_validator("languages", mode="before")
    @classmethod
    def validate_languages(cls, v: Any) -> list[str]:
        """Ensure languages is a list and normalize to lowercase."""
        if isinstance(v, str):
            v = [v]
        return [lang.lower() for lang in v]
    
    @property
    def boost_factor(self) -> float:
        """Get the trust-based scoring boost factor."""
        return self.trust_level.boost_factor
    
    def deactivate(self) -> None:
        """Soft-delete the source by marking it inactive."""
        self.active = False
        self.updated_at = datetime.utcnow()
    
    def reactivate(self) -> None:
        """Reactivate a soft-deleted source."""
        self.active = True
        self.updated_at = datetime.utcnow()
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "source_guid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                "group_guid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "name": "Reuters APAC",
                "type": "news_agency",
                "region": "APAC",
                "languages": ["en", "zh", "ja"],
                "trust_level": "high",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-12-08T00:00:00Z",
                "active": True,
                "metadata": {
                    "feed_url": "https://reuters.com/apac",
                    "update_frequency": "realtime",
                },
            }
        }
    }
