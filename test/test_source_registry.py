"""Tests for Source Registry - Phase 3.

Tests for CRUD operations on sources with flat storage (no group-based access).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.models import SourceMetadata, SourceType, TrustLevel
from app.services import (
    SourceNotFoundError,
    SourceRegistry,
)

# Add test directory to path for fixtures import
_test_dir = Path(__file__).parent
if str(_test_dir) not in sys.path:
    sys.path.insert(0, str(_test_dir))

from fixtures import DataStore  # noqa: E402 - path setup required before import


# =============================================================================
# Phase 3.1: Create and Get Sources
# =============================================================================


class TestCreateSource:
    """Tests for source creation."""

    def test_create_source_basic(self, data_store: DataStore) -> None:
        """Test creating a source with minimal required fields."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Test News Agency",
        )

        assert source.name == "Test News Agency"
        assert len(source.source_guid) == 36  # UUID format
        assert source.type == SourceType.OTHER  # Default
        assert source.trust_level == TrustLevel.UNVERIFIED  # Default
        assert source.active is True
        assert source.languages == ["en"]  # Default

    def test_create_source_with_all_fields(self, data_store: DataStore) -> None:
        """Test creating a source with all optional fields."""
        registry = SourceRegistry(data_store.base_path)

        metadata = SourceMetadata(
            feed_url="https://example.com/feed",
            update_frequency="hourly",
            department="Research",
        )

        source = registry.create(
            name="Reuters APAC",
            source_type=SourceType.NEWS_AGENCY,
            region="APAC",
            languages=["en", "zh", "ja"],
            trust_level=TrustLevel.HIGH,
            metadata=metadata,
        )

        assert source.name == "Reuters APAC"
        assert source.type == SourceType.NEWS_AGENCY
        assert source.region == "APAC"
        assert source.languages == ["en", "zh", "ja"]
        assert source.trust_level == TrustLevel.HIGH
        assert source.metadata is not None
        assert source.metadata.feed_url == "https://example.com/feed"

    def test_create_source_with_dict_metadata(self, data_store: DataStore) -> None:
        """Test creating a source with metadata as dict."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Internal Research",
            source_type=SourceType.INTERNAL,
            metadata={"department": "Equity Research"},
        )

        assert source.metadata is not None
        assert source.metadata.department == "Equity Research"

    def test_create_source_persists_to_file(self, data_store: DataStore) -> None:
        """Test that created source is persisted to disk with flat storage."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Persisted Source",
        )

        # Verify file exists in flat storage
        expected_path = (
            data_store.base_path
            / "sources"
            / f"{source.source_guid}.json"
        )
        assert expected_path.exists()

        # Verify content
        with expected_path.open() as f:
            data = json.load(f)
        assert data["name"] == "Persisted Source"
        assert data["source_guid"] == source.source_guid

    def test_create_source_writes_audit_log(self, data_store: DataStore) -> None:
        """Test that source creation writes an audit log entry."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Audited Source",
        )

        audit_log = registry.get_audit_log(source.source_guid)
        assert len(audit_log) == 1
        assert audit_log[0]["action"] == "create"
        assert audit_log[0]["source_guid"] == source.source_guid
        assert "initial" in audit_log[0]["changes"]


class TestGetSource:
    """Tests for source retrieval."""

    def test_get_source_by_guid(self, data_store: DataStore) -> None:
        """Test retrieving a source by GUID."""
        registry = SourceRegistry(data_store.base_path)

        created = registry.create(
            name="Test Source",
        )

        retrieved = registry.get(created.source_guid)

        assert retrieved.source_guid == created.source_guid
        assert retrieved.name == "Test Source"

    def test_get_source_not_found(self, data_store: DataStore) -> None:
        """Test getting a non-existent source raises error."""
        registry = SourceRegistry(data_store.base_path)

        with pytest.raises(SourceNotFoundError) as exc_info:
            registry.get("nonexistent-guid-0000-0000-000000000000")

        assert "nonexistent-guid-0000-0000-000000000000" in str(exc_info.value)

    def test_source_exists(self, data_store: DataStore) -> None:
        """Test exists method."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Exists Source",
        )

        assert registry.exists(source.source_guid) is True
        assert registry.exists("nonexistent-0000-0000-0000-000000000000") is False


# =============================================================================
# Phase 3.2: List Sources with Filters
# =============================================================================


class TestListSources:
    """Tests for listing sources with filters."""

    def test_list_sources_empty(self, data_store: DataStore) -> None:
        """Test listing sources when none exist."""
        registry = SourceRegistry(data_store.base_path)

        sources = registry.list_sources()

        assert sources == []

    def test_list_sources_all(self, data_store: DataStore) -> None:
        """Test listing all sources."""
        registry = SourceRegistry(data_store.base_path)

        # Create multiple sources
        registry.create(name="Source 1")
        registry.create(name="Source 2")
        registry.create(name="Source 3")

        sources = registry.list_sources()

        assert len(sources) == 3

    def test_filter_sources_by_region(self, data_store: DataStore) -> None:
        """Test filtering sources by region."""
        registry = SourceRegistry(data_store.base_path)

        registry.create(
            name="APAC Source",
            region="APAC",
        )
        registry.create(
            name="EMEA Source",
            region="EMEA",
        )
        registry.create(
            name="Americas Source",
            region="Americas",
        )

        apac_sources = registry.list_sources(region="APAC")

        assert len(apac_sources) == 1
        assert apac_sources[0].name == "APAC Source"
        assert apac_sources[0].region == "APAC"

    def test_filter_sources_by_type(self, data_store: DataStore) -> None:
        """Test filtering sources by source type."""
        registry = SourceRegistry(data_store.base_path)

        registry.create(
            name="News Agency",
            source_type=SourceType.NEWS_AGENCY,
        )
        registry.create(
            name="Internal Research",
            source_type=SourceType.INTERNAL,
        )
        registry.create(
            name="Government Report",
            source_type=SourceType.GOVERNMENT,
        )

        news_sources = registry.list_sources(source_type=SourceType.NEWS_AGENCY)

        assert len(news_sources) == 1
        assert news_sources[0].type == SourceType.NEWS_AGENCY

    def test_count_sources(self, data_store: DataStore) -> None:
        """Test counting sources."""
        registry = SourceRegistry(data_store.base_path)

        registry.create(name="Source 1")
        registry.create(name="Source 2")

        assert registry.count_sources() == 2


# =============================================================================
# Phase 3.3: Update Source (Audit Logged)
# =============================================================================


class TestUpdateSource:
    """Tests for updating sources."""

    def test_update_source_name(self, data_store: DataStore) -> None:
        """Test updating a source's name."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Original Name",
        )

        updated = registry.update(source.source_guid, name="Updated Name")

        assert updated.name == "Updated Name"
        assert updated.source_guid == source.source_guid

    def test_update_source_multiple_fields(self, data_store: DataStore) -> None:
        """Test updating multiple fields at once."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Original",
            source_type=SourceType.OTHER,
            trust_level=TrustLevel.UNVERIFIED,
        )

        updated = registry.update(
            source.source_guid,
            name="Updated",
            source_type=SourceType.NEWS_AGENCY,
            region="APAC",
            languages=["en", "zh"],
            trust_level=TrustLevel.HIGH,
        )

        assert updated.name == "Updated"
        assert updated.type == SourceType.NEWS_AGENCY
        assert updated.region == "APAC"
        assert updated.languages == ["en", "zh"]
        assert updated.trust_level == TrustLevel.HIGH

    def test_update_source_updates_timestamp(self, data_store: DataStore) -> None:
        """Test that update changes the updated_at timestamp."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Original",
        )
        original_updated_at = source.updated_at

        updated = registry.update(source.source_guid, name="Updated")

        assert updated.updated_at >= original_updated_at

    def test_update_creates_audit(self, data_store: DataStore) -> None:
        """Test that update creates an audit log entry."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Original Name",
        )

        registry.update(source.source_guid, name="Updated Name")

        audit_log = registry.get_audit_log(source.source_guid)

        # Should have 2 entries: create and update
        assert len(audit_log) == 2
        assert audit_log[0]["action"] == "update"  # Newest first
        assert audit_log[0]["changes"]["name"]["old"] == "Original Name"
        assert audit_log[0]["changes"]["name"]["new"] == "Updated Name"

    def test_update_nonexistent_source(self, data_store: DataStore) -> None:
        """Test updating a non-existent source raises error."""
        registry = SourceRegistry(data_store.base_path)

        with pytest.raises(SourceNotFoundError):
            registry.update(
                "nonexistent-0000-0000-0000-000000000000",
                name="New Name",
            )


# =============================================================================
# Phase 3.4: Soft-Delete Source
# =============================================================================


class TestSoftDeleteSource:
    """Tests for soft-deleting sources."""

    def test_soft_delete_source(self, data_store: DataStore) -> None:
        """Test soft-deleting a source."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="To Delete",
        )
        assert source.active is True

        deleted = registry.soft_delete(source.source_guid)

        assert deleted.active is False
        assert deleted.source_guid == source.source_guid

    def test_soft_delete_persists(self, data_store: DataStore) -> None:
        """Test that soft-delete is persisted."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="To Delete",
        )

        registry.soft_delete(source.source_guid)

        # Reload from disk
        reloaded = registry.get(source.source_guid)
        assert reloaded.active is False

    def test_soft_delete_excluded_from_list(self, data_store: DataStore) -> None:
        """Test that soft-deleted sources are excluded from list by default."""
        registry = SourceRegistry(data_store.base_path)

        source1 = registry.create(
            name="Active Source",
        )
        source2 = registry.create(
            name="Deleted Source",
        )

        registry.soft_delete(source2.source_guid)

        sources = registry.list_sources()

        assert len(sources) == 1
        assert sources[0].source_guid == source1.source_guid

    def test_soft_delete_include_inactive(self, data_store: DataStore) -> None:
        """Test including soft-deleted sources in list."""
        registry = SourceRegistry(data_store.base_path)

        registry.create(
            name="Active Source",
        )
        source2 = registry.create(
            name="Deleted Source",
        )

        registry.soft_delete(source2.source_guid)

        sources = registry.list_sources(include_inactive=True)

        assert len(sources) == 2

    def test_soft_delete_creates_audit(self, data_store: DataStore) -> None:
        """Test that soft-delete creates an audit log entry."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="To Delete",
        )

        registry.soft_delete(source.source_guid)

        audit_log = registry.get_audit_log(source.source_guid)

        assert len(audit_log) == 2
        assert audit_log[0]["action"] == "soft_delete"
        assert audit_log[0]["changes"]["active"]["old"] is True
        assert audit_log[0]["changes"]["active"]["new"] is False


# =============================================================================
# All tests complete - sources are now standalone entities
# =============================================================================
