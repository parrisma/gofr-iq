"""Tests for Pydantic models - Phase 1 of implementation.

This module tests the data models for groups, sources, documents, and queries.

Phase 1 Steps:
    1.1 - Source model
    1.2 - Document model with versioning
    1.3 - Word count validation
    1.4 - Query request/response models
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import (
    MAX_WORD_COUNT,
    Document,
    DocumentCreate,
    DocumentResult,
    DocumentUpdate,
    Group,
    GroupMetadata,
    Permission,
    QueryFilters,
    QueryRequest,
    QueryResponse,
    ScoringWeights,
    SimilarityMode,
    Source,
    SourceMetadata,
    SourceType,
    TrustLevel,
    count_words,
    validate_word_count,
)


class TestGroupModel:
    """Tests for Group model - Phase 1, Step 1.1 (Group)"""
    
    def test_group_model_valid(self) -> None:
        """Test creating a valid group."""
        group = Group(
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            name="APAC Research",
            description="Asia-Pacific research documents",
        )
        
        assert group.group_guid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert group.name == "APAC Research"
        assert group.active is True
        assert isinstance(group.created_at, datetime)
    
    def test_group_model_invalid_guid(self) -> None:
        """Test that invalid GUIDs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Group(
                group_guid="invalid-guid",
                name="Test Group",
            )
        assert "group_guid" in str(exc_info.value)
    
    def test_group_model_empty_name(self) -> None:
        """Test that empty names are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Group(
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                name="",
            )
        assert "name" in str(exc_info.value)
    
    def test_group_token_permissions(self) -> None:
        """Test token permission handling."""
        group = Group(
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            name="Test Group",
            tokens={
                "token_001": [Permission.CREATE, Permission.READ],
                "token_002": [Permission.READ],
            },
        )
        
        assert group.has_permission("token_001", Permission.CREATE)
        assert group.has_permission("token_001", Permission.READ)
        assert not group.has_permission("token_001", Permission.DELETE)
        assert not group.has_permission("token_003", Permission.READ)
    
    def test_group_token_permissions_from_strings(self) -> None:
        """Test that string permissions are converted to enums."""
        group = Group(
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            name="Test Group",
            tokens={
                "token_001": ["create", "read", "update", "delete"],  # type: ignore[list-item]
            },
        )
        
        assert group.has_permission("token_001", Permission.CREATE)
        assert group.has_permission("token_001", Permission.DELETE)
    
    def test_group_get_permissions(self) -> None:
        """Test getting all permissions for a token."""
        group = Group(
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            name="Test Group",
            tokens={
                "token_001": [Permission.CREATE, Permission.READ],
            },
        )
        
        perms = group.get_permissions("token_001")
        assert Permission.CREATE in perms
        assert Permission.READ in perms
        assert len(perms) == 2
        
        # Unknown token returns empty list
        assert group.get_permissions("unknown") == []
    
    def test_group_add_token(self) -> None:
        """Test adding a token to a group."""
        group = Group(
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            name="Test Group",
        )
        
        old_updated = group.updated_at
        group.add_token("new_token", [Permission.READ])
        
        assert group.has_permission("new_token", Permission.READ)
        assert group.updated_at >= old_updated
    
    def test_group_remove_token(self) -> None:
        """Test removing a token from a group."""
        group = Group(
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            name="Test Group",
            tokens={"token_001": [Permission.READ]},
        )
        
        assert group.remove_token("token_001") is True
        assert not group.has_permission("token_001", Permission.READ)
        
        # Removing non-existent token returns False
        assert group.remove_token("unknown") is False
    
    def test_group_metadata(self) -> None:
        """Test group metadata handling."""
        group = Group(
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            name="Test Group",
            metadata=GroupMetadata(region="APAC", department="Research"),
        )
        
        assert group.metadata is not None
        assert group.metadata.region == "APAC"
        assert group.metadata.department == "Research"
    
    def test_group_serialization(self) -> None:
        """Test group JSON serialization."""
        group = Group(
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            name="Test Group",
            tokens={"token_001": [Permission.READ]},
        )
        
        data = group.model_dump(mode="json")
        
        assert data["group_guid"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert data["tokens"]["token_001"] == ["read"]


class TestSourceModel:
    """Tests for Source model - Phase 1, Step 1.1 (Source)"""
    
    def test_source_model_valid(self) -> None:
        """Test creating a valid source."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Reuters APAC",
            type=SourceType.NEWS_AGENCY,
            trust_level=TrustLevel.HIGH,
        )
        
        assert source.source_guid == "7c9e6679-7425-40de-944b-e07fc1f90ae7"
        assert source.name == "Reuters APAC"
        assert source.type == SourceType.NEWS_AGENCY
        assert source.trust_level == TrustLevel.HIGH
        assert source.active is True
    
    def test_source_model_invalid_guid(self) -> None:
        """Test that invalid source GUIDs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Source(
                source_guid="invalid",
                name="Test Source",
            )
        assert "source_guid" in str(exc_info.value)
    
    def test_source_type_from_string(self) -> None:
        """Test that string types are converted to SourceType enum."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
            type="news_agency",  # type: ignore[arg-type]
        )
        
        assert source.type == SourceType.NEWS_AGENCY
    
    def test_source_trust_level_from_string(self) -> None:
        """Test that string trust levels are converted to TrustLevel enum."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
            trust_level="high",  # type: ignore[arg-type]
        )
        
        assert source.trust_level == TrustLevel.HIGH
    
    def test_source_boost_factor(self) -> None:
        """Test trust level boost factors."""
        assert TrustLevel.HIGH.boost_factor == 1.2
        assert TrustLevel.MEDIUM.boost_factor == 1.0
        assert TrustLevel.LOW.boost_factor == 0.8
        assert TrustLevel.UNVERIFIED.boost_factor == 0.6
        
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
            trust_level=TrustLevel.HIGH,
        )
        assert source.boost_factor == 1.2
    
    def test_source_languages_normalization(self) -> None:
        """Test that languages are normalized to lowercase."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
            languages=["EN", "ZH", "JA"],
        )
        
        assert source.languages == ["en", "zh", "ja"]
    
    def test_source_languages_from_string(self) -> None:
        """Test that single language string is converted to list."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
            languages="en",  # type: ignore[arg-type]
        )
        
        assert source.languages == ["en"]
    
    def test_source_deactivate(self) -> None:
        """Test soft-delete via deactivate."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
        )
        
        assert source.active is True
        old_updated = source.updated_at
        
        source.deactivate()
        
        assert source.active is False
        assert source.updated_at >= old_updated
    
    def test_source_reactivate(self) -> None:
        """Test reactivating a soft-deleted source."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
            active=False,
        )
        
        source.reactivate()
        
        assert source.active is True
    
    def test_source_metadata(self) -> None:
        """Test source metadata handling."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
            metadata=SourceMetadata(
                feed_url="https://example.com/feed",
                update_frequency="realtime",
            ),
        )
        
        assert source.metadata is not None
        assert source.metadata.feed_url == "https://example.com/feed"
    
    def test_source_serialization(self) -> None:
        """Test source JSON serialization."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
            type=SourceType.NEWS_AGENCY,
            trust_level=TrustLevel.HIGH,
        )
        
        data = source.model_dump(mode="json")
        
        assert data["source_guid"] == "7c9e6679-7425-40de-944b-e07fc1f90ae7"
        assert data["type"] == "news_agency"
        assert data["trust_level"] == "high"
    
    def test_source_default_values(self) -> None:
        """Test source default values."""
        source = Source(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            name="Test Source",
        )
        
        assert source.type == SourceType.OTHER
        assert source.trust_level == TrustLevel.UNVERIFIED
        assert source.languages == ["en"]
        assert source.active is True


class TestDocumentModel:
    """Tests for Document model - Phase 1, Step 1.2"""
    
    def test_document_model_valid(self) -> None:
        """Test creating a valid document."""
        doc = Document(
            guid="550e8400-e29b-41d4-a716-446655440000",
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Market Analysis Q4 2025",
            content="This is the full text content of the document.",
        )
        
        assert doc.guid == "550e8400-e29b-41d4-a716-446655440000"
        assert doc.version == 1
        assert doc.previous_version_guid is None
        assert doc.is_original is True
        assert doc.is_duplicate is False
    
    def test_document_model_invalid_guid(self) -> None:
        """Test that invalid GUIDs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Document(
                guid="invalid",
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                title="Test",
                content="Content",
            )
        assert "guid" in str(exc_info.value)
    
    def test_document_model_empty_title(self) -> None:
        """Test that empty titles are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                title="",
                content="Content",
            )
        assert "title" in str(exc_info.value)
    
    def test_document_model_empty_content(self) -> None:
        """Test that empty content is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                title="Test Title",
                content="",
            )
        assert "content" in str(exc_info.value)
    
    def test_document_version_chain_v1_no_previous(self) -> None:
        """Test version 1 documents cannot have previous_version_guid."""
        with pytest.raises(ValidationError) as exc_info:
            Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                title="Test",
                content="Content",
                version=1,
                previous_version_guid="550e8400-e29b-41d4-a716-446655440000",
            )
        assert "Version 1" in str(exc_info.value)
    
    def test_document_version_chain_v2_requires_previous(self) -> None:
        """Test version > 1 documents must have previous_version_guid."""
        with pytest.raises(ValidationError) as exc_info:
            Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                title="Test",
                content="Content",
                version=2,
                previous_version_guid=None,
            )
        assert "Version > 1" in str(exc_info.value)
    
    def test_document_create_new_version(self) -> None:
        """Test creating a new version of a document."""
        doc_v1 = Document(
            guid="550e8400-e29b-41d4-a716-446655440000",
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Original Title",
            content="Original content.",
        )
        
        doc_v2 = doc_v1.create_new_version(
            title="Updated Title",
            content="Updated content with more words.",
        )
        
        assert doc_v2.version == 2
        assert doc_v2.previous_version_guid == doc_v1.guid
        assert doc_v2.guid != doc_v1.guid
        assert doc_v2.title == "Updated Title"
        assert doc_v2.content == "Updated content with more words."
        assert doc_v2.is_original is False
    
    def test_document_create_new_version_partial(self) -> None:
        """Test creating a new version with only some fields updated."""
        doc_v1 = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Original Title",
            content="Original content.",
            metadata={"key": "value"},
        )
        
        doc_v2 = doc_v1.create_new_version(title="Only Title Changed")
        
        assert doc_v2.title == "Only Title Changed"
        assert doc_v2.content == "Original content."
        assert doc_v2.metadata == {"key": "value"}
    
    def test_document_duplicate_detection(self) -> None:
        """Test duplicate detection fields."""
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
            duplicate_of="440e8400-e29b-41d4-a716-446655440000",
            duplicate_score=0.97,
        )
        
        assert doc.is_duplicate is True
        assert doc.is_original is False
        assert doc.duplicate_of == "440e8400-e29b-41d4-a716-446655440000"
        assert doc.duplicate_score == 0.97
    
    def test_document_duplicate_validation_score_without_guid(self) -> None:
        """Test that duplicate_score requires duplicate_of."""
        with pytest.raises(ValidationError) as exc_info:
            Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                title="Test",
                content="Content",
                duplicate_score=0.95,
            )
        assert "duplicate_of must be set" in str(exc_info.value)
    
    def test_document_duplicate_validation_guid_without_score(self) -> None:
        """Test that duplicate_of requires duplicate_score > 0."""
        with pytest.raises(ValidationError) as exc_info:
            Document(
                source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                title="Test",
                content="Content",
                duplicate_of="440e8400-e29b-41d4-a716-446655440000",
                duplicate_score=0.0,
            )
        assert "duplicate_score must be > 0" in str(exc_info.value)
    
    def test_document_mark_as_duplicate(self) -> None:
        """Test marking a document as a duplicate."""
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
        )
        
        dup_doc = doc.mark_as_duplicate(
            original_guid="440e8400-e29b-41d4-a716-446655440000",
            score=0.95,
        )
        
        assert dup_doc.is_duplicate is True
        assert dup_doc.duplicate_of == "440e8400-e29b-41d4-a716-446655440000"
        assert dup_doc.duplicate_score == 0.95
        assert dup_doc.guid == doc.guid  # Same guid, just flagged
    
    def test_document_mark_as_duplicate_invalid_score(self) -> None:
        """Test that invalid scores are rejected when marking as duplicate."""
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
        )
        
        with pytest.raises(ValueError) as exc_info:
            doc.mark_as_duplicate(
                original_guid="440e8400-e29b-41d4-a716-446655440000",
                score=0.0,
            )
        assert "score must be between 0 and 1" in str(exc_info.value)
    
    def test_document_language_normalization(self) -> None:
        """Test that language is normalized."""
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
            language="EN",
        )
        
        assert doc.language == "en"
    
    def test_document_language_detected(self) -> None:
        """Test language_detected flag."""
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
            language="ja",
            language_detected=True,
        )
        
        assert doc.language_detected is True
        assert doc.language == "ja"
    
    def test_document_metadata(self) -> None:
        """Test document metadata handling."""
        doc = Document(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
            metadata={
                "author": "John Smith",
                "region": "APAC",
                "sectors": ["technology", "finance"],
                "companies": ["AAPL", "GOOGL"],
            },
        )
        
        assert doc.metadata["author"] == "John Smith"
        assert doc.metadata["sectors"] == ["technology", "finance"]
    
    def test_document_serialization(self) -> None:
        """Test document JSON serialization."""
        doc = Document(
            guid="550e8400-e29b-41d4-a716-446655440000",
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="Test",
            content="Content",
            version=1,
        )
        
        data = doc.model_dump(mode="json")
        
        assert data["guid"] == "550e8400-e29b-41d4-a716-446655440000"
        assert data["version"] == 1
        assert data["previous_version_guid"] is None
        assert isinstance(data["created_at"], str)


class TestDocumentCreate:
    """Tests for DocumentCreate schema - Phase 1, Step 1.2"""
    
    def test_document_create_valid(self) -> None:
        """Test creating a valid DocumentCreate."""
        create = DocumentCreate(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="New Document",
            content="This is the document content.",
        )
        
        assert create.source_guid == "7c9e6679-7425-40de-944b-e07fc1f90ae7"
        assert create.language is None  # Auto-detect
    
    def test_document_create_with_language(self) -> None:
        """Test creating DocumentCreate with explicit language."""
        create = DocumentCreate(
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            title="New Document",
            content="日本語のコンテンツ",
            language="ja",
        )
        
        assert create.language == "ja"
    
    def test_document_create_invalid_source_guid(self) -> None:
        """Test that invalid source GUID is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DocumentCreate(
                source_guid="invalid",
                group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                title="Test",
                content="Content",
            )
        assert "source_guid" in str(exc_info.value)


class TestDocumentUpdate:
    """Tests for DocumentUpdate schema - Phase 1, Step 1.2"""
    
    def test_document_update_all_fields(self) -> None:
        """Test updating all fields."""
        update = DocumentUpdate(
            title="Updated Title",
            content="Updated content.",
            metadata={"key": "new_value"},
        )
        
        assert update.title == "Updated Title"
        assert update.content == "Updated content."
        assert update.metadata == {"key": "new_value"}
    
    def test_document_update_partial(self) -> None:
        """Test updating only some fields."""
        update = DocumentUpdate(title="Only Title")
        
        assert update.title == "Only Title"
        assert update.content is None
        assert update.metadata is None


class TestWordCount:
    """Tests for word count functions - Phase 1, Step 1.3"""
    
    def test_count_words_empty(self) -> None:
        """Test counting words in empty string."""
        assert count_words("") == 0
    
    def test_count_words_single(self) -> None:
        """Test counting a single word."""
        assert count_words("hello") == 1
    
    def test_count_words_multiple(self) -> None:
        """Test counting multiple words."""
        assert count_words("hello world this is a test") == 6
    
    def test_count_words_with_punctuation(self) -> None:
        """Test counting words with punctuation."""
        assert count_words("Hello, world! How are you?") == 5
    
    def test_count_words_with_newlines(self) -> None:
        """Test counting words with newlines."""
        text = "Hello\nworld\nthis is\na test"
        assert count_words(text) == 6
    
    def test_validate_word_count_valid(self) -> None:
        """Test validating word count within limits."""
        content = "word " * 100
        is_valid, word_count = validate_word_count(content)
        
        assert is_valid is True
        assert word_count == 100
    
    def test_validate_word_count_at_limit(self) -> None:
        """Test validating word count at exact limit."""
        content = "word " * MAX_WORD_COUNT
        is_valid, word_count = validate_word_count(content)
        
        assert is_valid is True
        assert word_count == MAX_WORD_COUNT
    
    def test_validate_word_count_exceeds_limit(self) -> None:
        """Test validating word count exceeding limit."""
        content = "word " * (MAX_WORD_COUNT + 1)
        is_valid, word_count = validate_word_count(content)
        
        assert is_valid is False
        assert word_count == MAX_WORD_COUNT + 1
    
    def test_max_word_count_constant(self) -> None:
        """Test that MAX_WORD_COUNT is 20,000."""
        assert MAX_WORD_COUNT == 20_000


class TestQueryFilters:
    """Tests for QueryFilters model - Phase 1, Step 1.4"""
    
    def test_query_filters_empty(self) -> None:
        """Test empty filters."""
        filters = QueryFilters()
        
        assert filters.has_filters is False
        assert filters.date_from is None
        assert filters.regions is None
    
    def test_query_filters_with_dates(self) -> None:
        """Test filters with date range."""
        from datetime import datetime
        
        filters = QueryFilters(
            date_from=datetime(2025, 1, 1),
            date_to=datetime(2025, 12, 31),
        )
        
        assert filters.has_filters is True
        assert filters.date_from is not None
        assert filters.date_from.year == 2025
    
    def test_query_filters_invalid_date_range(self) -> None:
        """Test that invalid date ranges are rejected."""
        from datetime import datetime
        
        with pytest.raises(ValidationError) as exc_info:
            QueryFilters(
                date_from=datetime(2025, 12, 31),
                date_to=datetime(2025, 1, 1),
            )
        assert "date_from must be before date_to" in str(exc_info.value)
    
    def test_query_filters_normalize_lists(self) -> None:
        """Test that list values are normalized to lowercase."""
        filters = QueryFilters(
            regions=["APAC", "EMEA"],
            sectors=["TECHNOLOGY", "Finance"],
            languages=["EN", "ZH"],
        )
        
        assert filters.regions == ["apac", "emea"]
        assert filters.sectors == ["technology", "finance"]
        assert filters.languages == ["en", "zh"]
    
    def test_query_filters_has_filters(self) -> None:
        """Test has_filters property."""
        filters_empty = QueryFilters()
        filters_with_region = QueryFilters(regions=["apac"])
        
        assert filters_empty.has_filters is False
        assert filters_with_region.has_filters is True


class TestScoringWeights:
    """Tests for ScoringWeights model - Phase 1, Step 1.4"""
    
    def test_scoring_weights_defaults(self) -> None:
        """Test default scoring weights."""
        weights = ScoringWeights()
        
        assert weights.semantic == 0.5
        assert weights.keyword == 0.3
        assert weights.graph == 0.2
    
    def test_scoring_weights_custom(self) -> None:
        """Test custom scoring weights."""
        weights = ScoringWeights(semantic=0.7, keyword=0.2, graph=0.1)
        
        assert weights.semantic == 0.7
        assert weights.keyword == 0.2
        assert weights.graph == 0.1
    
    def test_scoring_weights_invalid_sum(self) -> None:
        """Test that weights must sum to 1.0."""
        with pytest.raises(ValidationError) as exc_info:
            ScoringWeights(semantic=0.5, keyword=0.5, graph=0.5)
        assert "sum to 1.0" in str(exc_info.value)
    
    def test_scoring_weights_out_of_range(self) -> None:
        """Test that weights must be between 0 and 1."""
        with pytest.raises(ValidationError) as exc_info:
            ScoringWeights(semantic=1.5, keyword=0.0, graph=0.0)
        assert "less than or equal to 1" in str(exc_info.value)


class TestQueryRequest:
    """Tests for QueryRequest model - Phase 1, Step 1.4"""
    
    def test_query_request_minimal(self) -> None:
        """Test minimal query request."""
        request = QueryRequest(query_text="market analysis APAC")
        
        assert request.query_text == "market analysis APAC"
        assert request.nearest_k == 10
        assert request.similarity_mode == SimilarityMode.HYBRID
        assert request.boost_recency is True
    
    def test_query_request_full(self) -> None:
        """Test full query request with all options."""
        request = QueryRequest(
            query_text="semiconductor companies",
            nearest_k=20,
            filters=QueryFilters(regions=["apac"], sectors=["technology"]),
            similarity_mode=SimilarityMode.SEMANTIC,
            scoring_weights=ScoringWeights(semantic=1.0, keyword=0.0, graph=0.0),
            include_duplicates=True,
            boost_recency=False,
            horizon_days=60,
        )
        
        assert request.nearest_k == 20
        assert request.similarity_mode == SimilarityMode.SEMANTIC
        assert request.filters is not None
        assert request.filters.regions == ["apac"]
        assert request.include_duplicates is True
        assert request.boost_recency is False
    
    def test_query_request_empty_text(self) -> None:
        """Test that empty query text is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(query_text="")
        assert "query_text" in str(exc_info.value)
    
    def test_query_request_text_too_long(self) -> None:
        """Test that overly long query text is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(query_text="x" * 5001)
        assert "query_text" in str(exc_info.value)
    
    def test_query_request_invalid_k(self) -> None:
        """Test that invalid nearest_k is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(query_text="test", nearest_k=0)
        assert "nearest_k" in str(exc_info.value)
        
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(query_text="test", nearest_k=101)
        assert "nearest_k" in str(exc_info.value)
    
    def test_query_request_effective_weights(self) -> None:
        """Test effective_weights property."""
        request_no_weights = QueryRequest(query_text="test")
        request_with_weights = QueryRequest(
            query_text="test",
            scoring_weights=ScoringWeights(semantic=0.8, keyword=0.1, graph=0.1),
        )
        
        assert request_no_weights.effective_weights.semantic == 0.5
        assert request_with_weights.effective_weights.semantic == 0.8
    
    def test_query_request_similarity_modes(self) -> None:
        """Test all similarity modes."""
        for mode in SimilarityMode:
            request = QueryRequest(query_text="test", similarity_mode=mode)
            assert request.similarity_mode == mode


class TestDocumentResult:
    """Tests for DocumentResult model - Phase 1, Step 1.4"""
    
    def test_document_result_minimal(self) -> None:
        """Test minimal document result."""
        result = DocumentResult(
            guid="550e8400-e29b-41d4-a716-446655440000",
            title="Market Report",
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            language="en",
            created_at=datetime.now(),
            score=0.95,
        )
        
        assert result.score == 0.95
        assert result.is_duplicate is False
    
    def test_document_result_with_breakdown(self) -> None:
        """Test document result with score breakdown."""
        result = DocumentResult(
            guid="550e8400-e29b-41d4-a716-446655440000",
            title="Market Report",
            source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            language="en",
            created_at=datetime.now(),
            score=0.85,
            score_breakdown={
                "semantic": 0.9,
                "keyword": 0.7,
                "graph": 0.8,
                "recency_boost": 1.1,
                "trust_boost": 1.2,
            },
        )
        
        assert result.score_breakdown["semantic"] == 0.9
        assert result.score_breakdown["trust_boost"] == 1.2


class TestQueryResponse:
    """Tests for QueryResponse model - Phase 1, Step 1.4"""
    
    def test_query_response_empty(self) -> None:
        """Test empty query response."""
        response = QueryResponse(query_text="test query")
        
        assert response.count == 0
        assert response.total_found == 0
        assert response.has_more is False
    
    def test_query_response_with_results(self) -> None:
        """Test query response with results."""
        results = [
            DocumentResult(
                guid=f"guid-{i}",
                title=f"Document {i}",
                source_guid="source-guid-001",
                group_guid="group-guid-001",
                language="en",
                created_at=datetime.now(),
                score=0.9 - (i * 0.1),
            )
            for i in range(5)
        ]
        
        response = QueryResponse(
            query_text="test query",
            results=results,
            total_found=100,
            took_ms=45.5,
        )
        
        assert response.count == 5
        assert response.total_found == 100
        assert response.has_more is True
        assert response.took_ms == 45.5
    
    def test_query_response_to_summary(self) -> None:
        """Test query response summary."""
        response = QueryResponse(
            query_text="market analysis",
            results=[],
            total_found=50,
            took_ms=30.0,
            similarity_mode=SimilarityMode.HYBRID,
        )
        
        summary = response.to_summary()
        
        assert summary["query_text"] == "market analysis"
        assert summary["results_returned"] == 0
        assert summary["total_found"] == 50
        assert summary["took_ms"] == 30.0
        assert summary["similarity_mode"] == "hybrid"
    
    def test_query_response_summary_truncates_long_query(self) -> None:
        """Test that long query text is truncated in summary."""
        long_query = "x" * 200
        response = QueryResponse(query_text=long_query)
        
        summary = response.to_summary()
        assert len(summary["query_text"]) == 103  # 100 + "..."


class TestSimilarityMode:
    """Tests for SimilarityMode enum - Phase 1, Step 1.4"""
    
    def test_similarity_mode_values(self) -> None:
        """Test similarity mode enum values."""
        assert SimilarityMode.SEMANTIC.value == "semantic"
        assert SimilarityMode.KEYWORD.value == "keyword"
        assert SimilarityMode.HYBRID.value == "hybrid"
    
    def test_similarity_mode_from_string(self) -> None:
        """Test creating similarity mode from string."""
        assert SimilarityMode("semantic") == SimilarityMode.SEMANTIC
        assert SimilarityMode("hybrid") == SimilarityMode.HYBRID
