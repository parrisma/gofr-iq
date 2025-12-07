"""Tests for Source Registry - Phase 3.

Tests for CRUD operations on sources with group-based access control.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.models import SourceMetadata, SourceType, TrustLevel
from app.services import (
    SourceAccessDeniedError,
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )

        assert source.name == "Test News Agency"
        assert source.group_guid == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            source_type=SourceType.INTERNAL,
            metadata={"department": "Equity Research"},
        )

        assert source.metadata is not None
        assert source.metadata.department == "Equity Research"

    def test_create_source_persists_to_file(self, data_store: DataStore) -> None:
        """Test that created source is persisted to disk."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Persisted Source",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )

        # Verify file exists
        expected_path = (
            data_store.base_path
            / "sources"
            / source.group_guid
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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

    def test_get_source_with_access_groups(self, data_store: DataStore) -> None:
        """Test getting a source with access group restriction."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Group A Source",
            group_guid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )

        # Can access with correct group
        retrieved = registry.get(
            source.source_guid,
            access_groups=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
        )
        assert retrieved.source_guid == source.source_guid

    def test_source_exists(self, data_store: DataStore) -> None:
        """Test exists method."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Exists Source",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
        registry.create(name="Source 1", group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        registry.create(name="Source 2", group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        registry.create(name="Source 3", group_guid="b2c3d4e5-f6a7-8901-bcde-f12345678901")

        sources = registry.list_sources()

        assert len(sources) == 3

    def test_list_sources_by_group(self, data_store: DataStore) -> None:
        """Test filtering sources by group."""
        registry = SourceRegistry(data_store.base_path)

        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        group_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        registry.create(name="Group A Source 1", group_guid=group_a)
        registry.create(name="Group A Source 2", group_guid=group_a)
        registry.create(name="Group B Source 1", group_guid=group_b)

        sources = registry.list_sources(group_guid=group_a)

        assert len(sources) == 2
        assert all(s.group_guid == group_a for s in sources)

    def test_filter_sources_by_region(self, data_store: DataStore) -> None:
        """Test filtering sources by region."""
        registry = SourceRegistry(data_store.base_path)

        registry.create(
            name="APAC Source",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            region="APAC",
        )
        registry.create(
            name="EMEA Source",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            region="EMEA",
        )
        registry.create(
            name="Americas Source",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            source_type=SourceType.NEWS_AGENCY,
        )
        registry.create(
            name="Internal Research",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            source_type=SourceType.INTERNAL,
        )
        registry.create(
            name="Government Report",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            source_type=SourceType.GOVERNMENT,
        )

        news_sources = registry.list_sources(source_type=SourceType.NEWS_AGENCY)

        assert len(news_sources) == 1
        assert news_sources[0].type == SourceType.NEWS_AGENCY

    def test_list_sources_with_access_groups(self, data_store: DataStore) -> None:
        """Test listing sources limited to access groups."""
        registry = SourceRegistry(data_store.base_path)

        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        group_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        group_c = "cccccccc-cccc-cccc-cccc-cccccccccccc"

        registry.create(name="A1", group_guid=group_a)
        registry.create(name="B1", group_guid=group_b)
        registry.create(name="C1", group_guid=group_c)

        # User has access to groups A and B only
        sources = registry.list_sources(access_groups=[group_a, group_b])

        assert len(sources) == 2
        names = {s.name for s in sources}
        assert names == {"A1", "B1"}

    def test_count_sources(self, data_store: DataStore) -> None:
        """Test counting sources."""
        registry = SourceRegistry(data_store.base_path)

        registry.create(name="Source 1", group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        registry.create(name="Source 2", group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890")

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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )

        updated = registry.update(source.source_guid, name="Updated Name")

        assert updated.name == "Updated Name"
        assert updated.source_guid == source.source_guid

    def test_update_source_multiple_fields(self, data_store: DataStore) -> None:
        """Test updating multiple fields at once."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Original",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )
        original_updated_at = source.updated_at

        updated = registry.update(source.source_guid, name="Updated")

        assert updated.updated_at >= original_updated_at

    def test_update_creates_audit(self, data_store: DataStore) -> None:
        """Test that update creates an audit log entry."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="Original Name",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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

    def test_update_with_access_groups(self, data_store: DataStore) -> None:
        """Test updating with access group authorization."""
        registry = SourceRegistry(data_store.base_path)

        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        source = registry.create(name="Test", group_guid=group_a)

        # Update with correct access group
        updated = registry.update(
            source.source_guid,
            access_groups=[group_a],
            name="Updated",
        )

        assert updated.name == "Updated"


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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )
        source2 = registry.create(
            name="Deleted Source",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )
        source2 = registry.create(
            name="Deleted Source",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )

        registry.soft_delete(source2.source_guid)

        sources = registry.list_sources(include_inactive=True)

        assert len(sources) == 2

    def test_soft_delete_creates_audit(self, data_store: DataStore) -> None:
        """Test that soft-delete creates an audit log entry."""
        registry = SourceRegistry(data_store.base_path)

        source = registry.create(
            name="To Delete",
            group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )

        registry.soft_delete(source.source_guid)

        audit_log = registry.get_audit_log(source.source_guid)

        assert len(audit_log) == 2
        assert audit_log[0]["action"] == "soft_delete"
        assert audit_log[0]["changes"]["active"]["old"] is True
        assert audit_log[0]["changes"]["active"]["new"] is False


# =============================================================================
# Phase 3.5: Access Groups Enforcement
# =============================================================================


class TestSourceAccessControl:
    """Tests for group-based access control."""

    def test_source_access_denied(self, data_store: DataStore) -> None:
        """Test that access is denied when source's group not in access_groups."""
        registry = SourceRegistry(data_store.base_path)

        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        group_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        source = registry.create(name="Group A Source", group_guid=group_a)

        # Try to access with only group B
        with pytest.raises(SourceAccessDeniedError) as exc_info:
            registry.get(source.source_guid, access_groups=[group_b])

        assert source.source_guid in str(exc_info.value)

    def test_source_access_allowed(self, data_store: DataStore) -> None:
        """Test that access is allowed when source's group is in access_groups."""
        registry = SourceRegistry(data_store.base_path)

        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        group_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        source = registry.create(name="Group A Source", group_guid=group_a)

        # Access with both groups
        retrieved = registry.get(source.source_guid, access_groups=[group_a, group_b])

        assert retrieved.source_guid == source.source_guid

    def test_update_access_denied(self, data_store: DataStore) -> None:
        """Test that update is denied without proper access."""
        registry = SourceRegistry(data_store.base_path)

        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        group_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        source = registry.create(name="Group A Source", group_guid=group_a)

        with pytest.raises(SourceAccessDeniedError):
            registry.update(
                source.source_guid,
                access_groups=[group_b],
                name="Unauthorized Update",
            )

    def test_soft_delete_access_denied(self, data_store: DataStore) -> None:
        """Test that soft-delete is denied without proper access."""
        registry = SourceRegistry(data_store.base_path)

        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        group_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        source = registry.create(name="Group A Source", group_guid=group_a)

        with pytest.raises(SourceAccessDeniedError):
            registry.soft_delete(source.source_guid, access_groups=[group_b])

    def test_no_access_groups_allows_all(self, data_store: DataStore) -> None:
        """Test that omitting access_groups allows access to all sources."""
        registry = SourceRegistry(data_store.base_path)

        group_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        source = registry.create(name="Any Source", group_guid=group_a)

        # No access_groups means unrestricted access
        retrieved = registry.get(source.source_guid)

        assert retrieved.source_guid == source.source_guid
