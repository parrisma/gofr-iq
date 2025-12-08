"""Tests for Audit Service - Phase 9.

Tests the audit logging system for the news repository.

Test Classes:
- TestAuditEntryModel: Tests for AuditEntry dataclass
- TestAuditServiceBasic: Basic audit logging operations
- TestAuditServiceQuery: Query and filtering tests
- TestAuditHelperFunctions: Convenience logging functions
- TestIngestAudit: Audit integration with ingest service
- TestSourceAudit: Audit integration with source registry
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from app.services import (
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

if TYPE_CHECKING:
    pass


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    """Create temporary audit directory."""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True)
    return audit_dir


@pytest.fixture
def audit_service(audit_path: Path) -> AuditService:
    """Create an AuditService instance."""
    return AuditService(base_path=audit_path)


@pytest.fixture
def group_guid() -> str:
    """Generate a group GUID."""
    return str(uuid.uuid4())


@pytest.fixture
def document_guid() -> str:
    """Generate a document GUID."""
    return str(uuid.uuid4())


@pytest.fixture
def source_guid() -> str:
    """Generate a source GUID."""
    return str(uuid.uuid4())


# =============================================================================
# TEST AUDIT ENTRY MODEL
# =============================================================================


class TestAuditEntryModel:
    """Tests for AuditEntry dataclass."""

    def test_create_audit_entry(self) -> None:
        """Test creating a basic audit entry."""
        entry = AuditEntry(
            event_type=AuditEventType.DOCUMENT_INGEST,
            timestamp=datetime.now(UTC),
            resource_guid="test-guid",
        )

        assert entry.event_type == AuditEventType.DOCUMENT_INGEST
        assert entry.resource_guid == "test-guid"
        assert entry.action_status == "success"

    def test_audit_entry_to_dict(self) -> None:
        """Test converting audit entry to dictionary."""
        ts = datetime(2025, 12, 8, 12, 0, 0, tzinfo=UTC)
        entry = AuditEntry(
            event_type=AuditEventType.SOURCE_CREATE,
            timestamp=ts,
            actor="test-user",
            group_guid="group-123",
            resource_guid="source-456",
            resource_type="source",
            details={"name": "Test Source"},
        )

        data = entry.to_dict()

        assert data["event_type"] == "source.create"
        assert data["actor"] == "test-user"
        assert data["group_guid"] == "group-123"
        assert data["resource_guid"] == "source-456"
        assert data["details"]["name"] == "Test Source"

    def test_audit_entry_to_json(self) -> None:
        """Test converting audit entry to JSON string."""
        entry = AuditEntry(
            event_type=AuditEventType.DOCUMENT_RETRIEVE,
            timestamp=datetime.now(UTC),
            resource_guid="doc-123",
        )

        json_str = entry.to_json()

        # Should be valid JSON
        data = json.loads(json_str)
        assert data["event_type"] == "document.retrieve"
        assert data["resource_guid"] == "doc-123"

    def test_audit_entry_from_dict(self) -> None:
        """Test creating audit entry from dictionary."""
        data = {
            "event_type": "document.ingest",
            "timestamp": "2025-12-08T12:00:00+00:00",
            "actor": "system",
            "resource_guid": "doc-123",
            "resource_type": "document",
            "action_status": "success",
            "details": {"language": "en"},
        }

        entry = AuditEntry.from_dict(data)

        assert entry.event_type == AuditEventType.DOCUMENT_INGEST
        assert entry.actor == "system"
        assert entry.details["language"] == "en"

    def test_audit_entry_from_json(self) -> None:
        """Test creating audit entry from JSON string."""
        json_str = json.dumps({
            "event_type": "source.update",
            "timestamp": "2025-12-08T12:00:00+00:00",
            "resource_guid": "source-123",
            "action_status": "success",
            "details": {},
        })

        entry = AuditEntry.from_json(json_str)

        assert entry.event_type == AuditEventType.SOURCE_UPDATE
        assert entry.resource_guid == "source-123"

    def test_audit_entry_immutable(self) -> None:
        """Test that audit entry is immutable (frozen dataclass)."""
        entry = AuditEntry(
            event_type=AuditEventType.DOCUMENT_INGEST,
            timestamp=datetime.now(UTC),
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            entry.actor = "changed"  # type: ignore


# =============================================================================
# TEST AUDIT SERVICE BASIC
# =============================================================================


class TestAuditServiceBasic:
    """Tests for basic audit service operations."""

    def test_create_audit_service(self, audit_path: Path) -> None:
        """Test creating audit service."""
        service = AuditService(base_path=audit_path)

        assert service.base_path == audit_path

    def test_log_entry(self, audit_service: AuditService) -> None:
        """Test logging a single entry."""
        entry = AuditEntry(
            event_type=AuditEventType.DOCUMENT_INGEST,
            timestamp=datetime.now(UTC),
            resource_guid="doc-123",
        )

        audit_service.log(entry)

        # Verify file was created
        today = date.today().isoformat()
        audit_file = audit_service.base_path / today / "audit.jsonl"
        assert audit_file.exists()

    def test_log_event_convenience(self, audit_service: AuditService) -> None:
        """Test log_event convenience method."""
        entry = audit_service.log_event(
            event_type=AuditEventType.SOURCE_CREATE,
            resource_guid="source-123",
            resource_type="source",
            actor="test-user",
        )

        assert entry.event_type == AuditEventType.SOURCE_CREATE
        assert entry.resource_guid == "source-123"
        assert entry.actor == "test-user"

    def test_log_multiple_entries(self, audit_service: AuditService) -> None:
        """Test logging multiple entries."""
        for i in range(5):
            audit_service.log_event(
                event_type=AuditEventType.DOCUMENT_RETRIEVE,
                resource_guid=f"doc-{i}",
            )

        entries = audit_service.query()
        assert len(entries) == 5

    def test_audit_service_repr(self, audit_service: AuditService) -> None:
        """Test string representation."""
        repr_str = repr(audit_service)
        assert "AuditService" in repr_str
        assert "base_path" in repr_str


# =============================================================================
# TEST AUDIT SERVICE QUERY
# =============================================================================


class TestAuditServiceQuery:
    """Tests for audit service query functionality."""

    def test_query_all_entries(self, audit_service: AuditService) -> None:
        """Test querying all entries."""
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_INGEST,
            resource_guid="doc-1",
        )
        audit_service.log_event(
            event_type=AuditEventType.SOURCE_CREATE,
            resource_guid="source-1",
        )

        entries = audit_service.query()
        assert len(entries) == 2

    def test_query_by_event_type(self, audit_service: AuditService) -> None:
        """Test filtering by event type."""
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_INGEST,
            resource_guid="doc-1",
        )
        audit_service.log_event(
            event_type=AuditEventType.SOURCE_CREATE,
            resource_guid="source-1",
        )
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_INGEST,
            resource_guid="doc-2",
        )

        entries = audit_service.query(event_type=AuditEventType.DOCUMENT_INGEST)
        assert len(entries) == 2

    def test_query_by_resource_guid(self, audit_service: AuditService) -> None:
        """Test filtering by resource GUID."""
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_RETRIEVE,
            resource_guid="doc-123",
        )
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_RETRIEVE,
            resource_guid="doc-456",
        )
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_RETRIEVE,
            resource_guid="doc-123",
        )

        entries = audit_service.query(resource_guid="doc-123")
        assert len(entries) == 2

    def test_query_by_group_guid(self, audit_service: AuditService) -> None:
        """Test filtering by group GUID."""
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_INGEST,
            resource_guid="doc-1",
            group_guid="group-A",
        )
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_INGEST,
            resource_guid="doc-2",
            group_guid="group-B",
        )

        entries = audit_service.query(group_guid="group-A")
        assert len(entries) == 1
        assert entries[0].resource_guid == "doc-1"

    def test_query_by_actor(self, audit_service: AuditService) -> None:
        """Test filtering by actor."""
        audit_service.log_event(
            event_type=AuditEventType.SOURCE_CREATE,
            actor="user-1",
        )
        audit_service.log_event(
            event_type=AuditEventType.SOURCE_CREATE,
            actor="user-2",
        )

        entries = audit_service.query(actor="user-1")
        assert len(entries) == 1

    def test_query_with_limit(self, audit_service: AuditService) -> None:
        """Test query with limit."""
        for i in range(10):
            audit_service.log_event(
                event_type=AuditEventType.DOCUMENT_RETRIEVE,
                resource_guid=f"doc-{i}",
            )

        entries = audit_service.query(limit=5)
        assert len(entries) == 5

    def test_count_entries(self, audit_service: AuditService) -> None:
        """Test counting entries."""
        for i in range(7):
            audit_service.log_event(
                event_type=AuditEventType.DOCUMENT_INGEST,
                resource_guid=f"doc-{i}",
            )

        count = audit_service.count()
        assert count == 7

    def test_count_by_event_type(self, audit_service: AuditService) -> None:
        """Test counting by event type."""
        for i in range(3):
            audit_service.log_event(
                event_type=AuditEventType.DOCUMENT_INGEST,
            )
        for i in range(5):
            audit_service.log_event(
                event_type=AuditEventType.SOURCE_CREATE,
            )

        count = audit_service.count(event_type=AuditEventType.SOURCE_CREATE)
        assert count == 5


# =============================================================================
# TEST AUDIT HELPER FUNCTIONS
# =============================================================================


class TestAuditHelperFunctions:
    """Tests for audit helper functions."""

    def test_log_document_ingest(
        self,
        audit_service: AuditService,
        document_guid: str,
        source_guid: str,
        group_guid: str,
    ) -> None:
        """Test log_document_ingest helper."""
        entry = log_document_ingest(
            service=audit_service,
            document_guid=document_guid,
            source_guid=source_guid,
            group_guid=group_guid,
            actor="ingest-system",
            is_duplicate=False,
            language="en",
            word_count=500,
        )

        assert entry.event_type == AuditEventType.DOCUMENT_INGEST
        assert entry.resource_guid == document_guid
        assert entry.group_guid == group_guid
        assert entry.details["source_guid"] == source_guid
        assert entry.details["language"] == "en"
        assert entry.details["word_count"] == 500

    def test_log_document_ingest_duplicate(
        self,
        audit_service: AuditService,
        group_guid: str,
    ) -> None:
        """Test log_document_ingest for duplicate document."""
        original_guid = str(uuid.uuid4())
        dup_guid = str(uuid.uuid4())

        entry = log_document_ingest(
            service=audit_service,
            document_guid=dup_guid,
            source_guid=str(uuid.uuid4()),
            group_guid=group_guid,
            is_duplicate=True,
            duplicate_of=original_guid,
        )

        assert entry.details["is_duplicate"] is True
        assert entry.details["duplicate_of"] == original_guid

    def test_log_document_retrieve(
        self,
        audit_service: AuditService,
        document_guid: str,
        group_guid: str,
    ) -> None:
        """Test log_document_retrieve helper."""
        entry = log_document_retrieve(
            service=audit_service,
            document_guid=document_guid,
            group_guid=group_guid,
            actor="analyst-user",
        )

        assert entry.event_type == AuditEventType.DOCUMENT_RETRIEVE
        assert entry.resource_guid == document_guid
        assert entry.actor == "analyst-user"

    def test_log_source_create(
        self,
        audit_service: AuditService,
        source_guid: str,
        group_guid: str,
    ) -> None:
        """Test log_source_create helper."""
        entry = log_source_create(
            service=audit_service,
            source_guid=source_guid,
            group_guid=group_guid,
            source_name="Reuters APAC",
            actor="admin-user",
        )

        assert entry.event_type == AuditEventType.SOURCE_CREATE
        assert entry.resource_guid == source_guid
        assert entry.details["name"] == "Reuters APAC"

    def test_log_source_update(
        self,
        audit_service: AuditService,
        source_guid: str,
        group_guid: str,
    ) -> None:
        """Test log_source_update helper."""
        changes = {"name": "Updated Name", "region": "JP"}

        entry = log_source_update(
            service=audit_service,
            source_guid=source_guid,
            group_guid=group_guid,
            changes=changes,
            actor="admin-user",
        )

        assert entry.event_type == AuditEventType.SOURCE_UPDATE
        assert entry.details["changes"] == changes

    def test_log_source_delete(
        self,
        audit_service: AuditService,
        source_guid: str,
        group_guid: str,
    ) -> None:
        """Test log_source_delete helper."""
        entry = log_source_delete(
            service=audit_service,
            source_guid=source_guid,
            group_guid=group_guid,
            actor="admin-user",
        )

        assert entry.event_type == AuditEventType.SOURCE_DELETE
        assert entry.resource_guid == source_guid

    def test_log_document_query(
        self,
        audit_service: AuditService,
    ) -> None:
        """Test log_document_query helper."""
        entry = log_document_query(
            service=audit_service,
            query_text="APAC market news",
            group_guids=["group-A", "group-B"],
            actor="analyst",
            result_count=15,
            filters={"language": "en", "region": "APAC"},
        )

        assert entry.event_type == AuditEventType.DOCUMENT_QUERY
        assert entry.details["query_text"] == "APAC market news"
        assert entry.details["result_count"] == 15
        assert entry.details["filters"]["language"] == "en"


# =============================================================================
# TEST CREATE AUDIT SERVICE FACTORY
# =============================================================================


class TestCreateAuditServiceFactory:
    """Tests for create_audit_service factory function."""

    def test_create_audit_service_function(self, audit_path: Path) -> None:
        """Test the factory function."""
        service = create_audit_service(audit_path)

        assert isinstance(service, AuditService)
        assert service.base_path == audit_path


# =============================================================================
# TEST AUDIT FILE MANAGEMENT
# =============================================================================


class TestAuditFileManagement:
    """Tests for audit file management."""

    def test_date_partitioned_storage(self, audit_service: AuditService) -> None:
        """Test that entries are stored in date-partitioned files."""
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_INGEST,
            resource_guid="doc-1",
        )

        today = date.today().isoformat()
        audit_file = audit_service.base_path / today / "audit.jsonl"

        assert audit_file.exists()
        assert audit_file.stat().st_size > 0

    def test_clear_date(self, audit_service: AuditService) -> None:
        """Test clearing entries for a specific date."""
        audit_service.log_event(
            event_type=AuditEventType.DOCUMENT_INGEST,
            resource_guid="doc-1",
        )

        today = date.today()
        result = audit_service.clear_date(today)

        assert result is True
        assert audit_service.count() == 0

    def test_clear_nonexistent_date(self, audit_service: AuditService) -> None:
        """Test clearing non-existent date returns False."""
        result = audit_service.clear_date(date(2020, 1, 1))
        assert result is False

    def test_jsonl_format(self, audit_service: AuditService) -> None:
        """Test that file is in JSONL format (one JSON per line)."""
        audit_service.log_event(event_type=AuditEventType.DOCUMENT_INGEST)
        audit_service.log_event(event_type=AuditEventType.SOURCE_CREATE)
        audit_service.log_event(event_type=AuditEventType.DOCUMENT_RETRIEVE)

        today = date.today().isoformat()
        audit_file = audit_service.base_path / today / "audit.jsonl"

        with audit_file.open("r") as f:
            lines = f.readlines()

        assert len(lines) == 3
        for line in lines:
            # Each line should be valid JSON
            data = json.loads(line.strip())
            assert "event_type" in data
            assert "timestamp" in data
