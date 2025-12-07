"""Document model for APAC Brokerage News Repository.

Documents are immutable - updates create new versions linked to the original.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class Document(BaseModel):
    """Document model - immutable, versioned news content.

    Documents are append-only. Updates create new versions with
    previous_version_guid linking to the original.

    Attributes:
        guid: Unique identifier for this document version
        version: Version number (1 for originals)
        previous_version_guid: GUID of previous version (None for v1)
        source_guid: GUID of the source that provided this document
        group_guid: GUID of the group this document belongs to
        created_at: When this version was created
        language: ISO 639-1 language code
        language_detected: True if language was auto-detected
        title: Document title
        content: Full text content (max 20,000 words)
        word_count: Number of words in content
        duplicate_of: GUID of original if this is a duplicate
        duplicate_score: Similarity score if duplicate (0.0-1.0)
        metadata: Additional document metadata
    """

    guid: str = Field(default_factory=lambda: str(uuid4()))
    version: int = Field(default=1, ge=1)
    previous_version_guid: str | None = Field(default=None)
    source_guid: str = Field(..., description="GUID of the source")
    group_guid: str = Field(..., description="GUID of the group")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    language: str = Field(default="en")
    language_detected: bool = Field(default=False)
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    word_count: int = Field(default=0, ge=0)
    duplicate_of: str | None = Field(default=None)
    duplicate_score: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("guid", "source_guid", "group_guid")
    @classmethod
    def validate_guid_format(cls, v: str, info: Any) -> str:
        """Validate GUID format."""
        if not v or len(v) < 32:
            raise ValueError(f"{info.field_name} must be a valid GUID")
        return v

    @field_validator("previous_version_guid", "duplicate_of")
    @classmethod
    def validate_optional_guid(cls, v: str | None, info: Any) -> str | None:
        """Validate optional GUID fields."""
        if v is not None and len(v) < 32:
            raise ValueError(f"{info.field_name} must be a valid GUID if provided")
        return v

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        """Validate and normalize language code."""
        return v.lower().strip()[:2] if v else "en"

    @model_validator(mode="after")
    def validate_version_chain(self) -> "Document":
        """Validate version and previous_version_guid consistency."""
        if self.version == 1 and self.previous_version_guid is not None:
            raise ValueError("Version 1 documents cannot have previous_version_guid")
        if self.version > 1 and self.previous_version_guid is None:
            raise ValueError("Version > 1 documents must have previous_version_guid")
        return self

    @model_validator(mode="after")
    def validate_duplicate_fields(self) -> "Document":
        """Validate duplicate_of and duplicate_score consistency."""
        if self.duplicate_of is not None and self.duplicate_score == 0.0:
            raise ValueError("duplicate_score must be > 0 when duplicate_of is set")
        if self.duplicate_of is None and self.duplicate_score > 0.0:
            raise ValueError("duplicate_of must be set when duplicate_score > 0")
        return self

    @property
    def is_duplicate(self) -> bool:
        """Check if this document is marked as a duplicate."""
        return self.duplicate_of is not None

    @property
    def is_original(self) -> bool:
        """Check if this is an original (non-duplicate) version 1 document."""
        return self.version == 1 and not self.is_duplicate

    def create_new_version(
        self,
        title: str | None = None,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Document":
        """Create a new version of this document.

        Args:
            title: New title (or keep existing)
            content: New content (or keep existing)
            metadata: New metadata (merged with existing)

        Returns:
            New Document instance with incremented version
        """
        new_metadata = {**self.metadata, **(metadata or {})}
        new_content = content if content is not None else self.content

        return Document(
            guid=str(uuid4()),
            version=self.version + 1,
            previous_version_guid=self.guid,
            source_guid=self.source_guid,
            group_guid=self.group_guid,
            language=self.language,
            language_detected=self.language_detected,
            title=title if title is not None else self.title,
            content=new_content,
            word_count=count_words(new_content),
            metadata=new_metadata,
        )

    def mark_as_duplicate(self, original_guid: str, score: float) -> "Document":
        """Create a copy of this document marked as a duplicate.

        Since documents are immutable, this returns a new Document instance.

        Args:
            original_guid: GUID of the original document
            score: Similarity score (0.0-1.0)

        Returns:
            New Document instance with duplicate fields set
        """
        if score <= 0.0 or score > 1.0:
            raise ValueError("Duplicate score must be between 0 and 1")

        return Document(
            guid=self.guid,
            version=self.version,
            previous_version_guid=self.previous_version_guid,
            source_guid=self.source_guid,
            group_guid=self.group_guid,
            created_at=self.created_at,
            language=self.language,
            language_detected=self.language_detected,
            title=self.title,
            content=self.content,
            word_count=self.word_count,
            duplicate_of=original_guid,
            duplicate_score=score,
            metadata=self.metadata,
        )


class DocumentCreate(BaseModel):
    """Schema for creating a new document.

    This is the input schema - word_count is computed from content.
    """

    source_guid: str = Field(..., description="GUID of the source")
    group_guid: str = Field(..., description="GUID of the group")
    language: str | None = Field(default=None, description="ISO 639-1 language code")
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_guid", "group_guid")
    @classmethod
    def validate_guid_format(cls, v: str, info: Any) -> str:
        """Validate GUID format."""
        if not v or len(v) < 32:
            raise ValueError(f"{info.field_name} must be a valid GUID")
        return v


class DocumentUpdate(BaseModel):
    """Schema for updating a document (creates new version).

    All fields are optional - only provided fields will be updated.
    """

    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] | None = Field(default=None)


# Constants
MAX_WORD_COUNT = 20_000


def count_words(text: str) -> int:
    """Count words in text.

    Args:
        text: The text to count words in

    Returns:
        Number of words
    """
    if not text:
        return 0
    return len(text.split())


def validate_word_count(content: str) -> tuple[bool, int]:
    """Validate that content is within word count limits.

    Args:
        content: The text content to validate

    Returns:
        Tuple of (is_valid, word_count)
    """
    word_count = count_words(content)
    return word_count <= MAX_WORD_COUNT, word_count
