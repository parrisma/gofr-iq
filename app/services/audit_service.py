"""Audit Service - Phase 9.

Full audit trail for all operations in the news repository.

Event Types:
- document.ingest: Document ingestion events
- document.query: Document query/search events  
- document.retrieve: Document retrieval by GUID
- source.create: Source creation
- source.update: Source update
- source.delete: Source soft-delete
- admin.rebuild: Index rebuild operations
- admin.group_change: Group permission changes

Storage: data/audit/{YYYY-MM-DD}/audit.jsonl (append-only JSONL format)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, date
from enum import Enum
from pathlib import Path
from typing import Any


class AuditEventType(str, Enum):
    """Types of audit events."""

    # Document events
    DOCUMENT_INGEST = "document.ingest"
    DOCUMENT_QUERY = "document.query"
    DOCUMENT_RETRIEVE = "document.retrieve"

    # Source events
    SOURCE_CREATE = "source.create"
    SOURCE_UPDATE = "source.update"
    SOURCE_DELETE = "source.delete"

    # Admin events
    ADMIN_REBUILD = "admin.rebuild"
    ADMIN_GROUP_CHANGE = "admin.group_change"


@dataclass(frozen=True)
class AuditEntry:
    """Immutable audit log entry.

    Attributes:
        event_type: Type of event (document.ingest, source.create, etc.)
        timestamp: When the event occurred (UTC)
        actor: User/system that performed the action (optional)
        group_guid: Group context for the action (optional)
        resource_guid: Primary resource affected (document/source GUID)
        resource_type: Type of resource (document, source, group)
        action_status: Outcome status (success, failure, etc.)
        details: Additional event-specific data
    """

    event_type: AuditEventType
    timestamp: datetime
    actor: str | None = None
    group_guid: str | None = None
    resource_guid: str | None = None
    resource_type: str | None = None
    action_status: str = "success"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "actor": self.actor,
            "group_guid": self.group_guid,
            "resource_guid": self.resource_guid,
            "resource_type": self.resource_type,
            "action_status": self.action_status,
            "details": self.details,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        """Create AuditEntry from dictionary."""
        return cls(
            event_type=AuditEventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            actor=data.get("actor"),
            group_guid=data.get("group_guid"),
            resource_guid=data.get("resource_guid"),
            resource_type=data.get("resource_type"),
            action_status=data.get("action_status", "success"),
            details=data.get("details", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AuditEntry":
        """Create AuditEntry from JSON string."""
        return cls.from_dict(json.loads(json_str))


# =============================================================================
# AUDIT SERVICE
# =============================================================================


class AuditService:
    """Service for logging audit events.

    Stores audit events in append-only JSONL files partitioned by date.
    Each day's events are stored in a separate file for efficient querying
    and archival.

    File path: {base_path}/{YYYY-MM-DD}/audit.jsonl

    Attributes:
        base_path: Base directory for audit storage
    """

    def __init__(self, base_path: Path | str) -> None:
        """Initialize audit service.

        Args:
            base_path: Base directory for audit storage
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_audit_path(self, dt: datetime | date | None = None) -> Path:
        """Get the audit file path for a given date.

        Args:
            dt: Date/datetime to get path for (defaults to today)

        Returns:
            Path to the audit JSONL file
        """
        if dt is None:
            dt = datetime.now(UTC)

        if isinstance(dt, datetime):
            date_str = dt.strftime("%Y-%m-%d")
        else:
            date_str = dt.isoformat()

        date_dir = self.base_path / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        return date_dir / "audit.jsonl"

    def log(self, entry: AuditEntry) -> None:
        """Log an audit entry.

        Appends the entry to the appropriate date-partitioned JSONL file.

        Args:
            entry: The audit entry to log
        """
        audit_path = self._get_audit_path(entry.timestamp)

        with audit_path.open("a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")

    def log_event(
        self,
        event_type: AuditEventType,
        resource_guid: str | None = None,
        resource_type: str | None = None,
        actor: str | None = None,
        group_guid: str | None = None,
        action_status: str = "success",
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Log an audit event with automatic timestamp.

        Convenience method for logging events without manually creating
        an AuditEntry.

        Args:
            event_type: Type of event
            resource_guid: Primary resource affected
            resource_type: Type of resource
            actor: User/system performing action
            group_guid: Group context
            action_status: Outcome status
            details: Additional event details

        Returns:
            The created AuditEntry
        """
        entry = AuditEntry(
            event_type=event_type,
            timestamp=datetime.now(UTC),
            actor=actor,
            group_guid=group_guid,
            resource_guid=resource_guid,
            resource_type=resource_type,
            action_status=action_status,
            details=details or {},
        )
        self.log(entry)
        return entry

    def query(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        event_type: AuditEventType | None = None,
        resource_guid: str | None = None,
        group_guid: str | None = None,
        actor: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filters.

        Args:
            start_date: Start date for query (inclusive)
            end_date: End date for query (inclusive)
            event_type: Filter by event type
            resource_guid: Filter by resource GUID
            group_guid: Filter by group GUID
            actor: Filter by actor
            limit: Maximum number of entries to return

        Returns:
            List of matching AuditEntry objects
        """
        entries: list[AuditEntry] = []

        # Default to today if no dates specified
        if start_date is None:
            start_date = date.today()
        if end_date is None:
            end_date = date.today()

        # Iterate through date range
        current = start_date
        while current <= end_date:
            audit_path = self._get_audit_path(current)
            if audit_path.exists():
                with audit_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue

                        entry = AuditEntry.from_json(line)

                        # Apply filters
                        if event_type and entry.event_type != event_type:
                            continue
                        if resource_guid and entry.resource_guid != resource_guid:
                            continue
                        if group_guid and entry.group_guid != group_guid:
                            continue
                        if actor and entry.actor != actor:
                            continue

                        entries.append(entry)

                        if limit and len(entries) >= limit:
                            return entries

            # Move to next day
            from datetime import timedelta

            current = current + timedelta(days=1)

        return entries

    def count(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        event_type: AuditEventType | None = None,
    ) -> int:
        """Count audit entries matching filters.

        Args:
            start_date: Start date for count
            end_date: End date for count
            event_type: Filter by event type

        Returns:
            Count of matching entries
        """
        entries = self.query(
            start_date=start_date,
            end_date=end_date,
            event_type=event_type,
        )
        return len(entries)

    def clear_date(self, dt: date) -> bool:
        """Clear all audit entries for a specific date.

        WARNING: This permanently deletes audit data. Use with caution.

        Args:
            dt: Date to clear

        Returns:
            True if file was deleted, False if it didn't exist
        """
        audit_path = self._get_audit_path(dt)
        if audit_path.exists():
            audit_path.unlink()
            return True
        return False

    def __repr__(self) -> str:
        """Return string representation."""
        return f"AuditService(base_path={self.base_path})"


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_audit_service(base_path: Path | str) -> AuditService:
    """Create an audit service instance.

    Args:
        base_path: Base directory for audit storage

    Returns:
        Configured AuditService instance
    """
    return AuditService(base_path=base_path)


# =============================================================================
# AUDIT HELPER FUNCTIONS FOR SPECIFIC EVENTS
# =============================================================================


def log_document_ingest(
    service: AuditService,
    document_guid: str,
    source_guid: str,
    group_guid: str,
    actor: str | None = None,
    is_duplicate: bool = False,
    duplicate_of: str | None = None,
    language: str | None = None,
    word_count: int | None = None,
) -> AuditEntry:
    """Log a document ingest event.

    Args:
        service: AuditService instance
        document_guid: GUID of the ingested document
        source_guid: GUID of the source
        group_guid: GUID of the group
        actor: User/system performing ingestion
        is_duplicate: Whether document was flagged as duplicate
        duplicate_of: Original document GUID if duplicate
        language: Detected/set language
        word_count: Document word count

    Returns:
        The created AuditEntry
    """
    details: dict[str, Any] = {
        "source_guid": source_guid,
        "is_duplicate": is_duplicate,
    }
    if duplicate_of:
        details["duplicate_of"] = duplicate_of
    if language:
        details["language"] = language
    if word_count is not None:
        details["word_count"] = word_count

    return service.log_event(
        event_type=AuditEventType.DOCUMENT_INGEST,
        resource_guid=document_guid,
        resource_type="document",
        actor=actor,
        group_guid=group_guid,
        details=details,
    )


def log_document_retrieve(
    service: AuditService,
    document_guid: str,
    group_guid: str,
    actor: str | None = None,
) -> AuditEntry:
    """Log a document retrieval event.

    Args:
        service: AuditService instance
        document_guid: GUID of retrieved document
        group_guid: GUID of the group
        actor: User/system retrieving document

    Returns:
        The created AuditEntry
    """
    return service.log_event(
        event_type=AuditEventType.DOCUMENT_RETRIEVE,
        resource_guid=document_guid,
        resource_type="document",
        actor=actor,
        group_guid=group_guid,
    )


def log_source_create(
    service: AuditService,
    source_guid: str,
    group_guid: str,
    source_name: str,
    actor: str | None = None,
) -> AuditEntry:
    """Log a source creation event.

    Args:
        service: AuditService instance
        source_guid: GUID of the created source
        group_guid: GUID of the group
        source_name: Name of the source
        actor: User/system creating source

    Returns:
        The created AuditEntry
    """
    return service.log_event(
        event_type=AuditEventType.SOURCE_CREATE,
        resource_guid=source_guid,
        resource_type="source",
        actor=actor,
        group_guid=group_guid,
        details={"name": source_name},
    )


def log_source_update(
    service: AuditService,
    source_guid: str,
    group_guid: str,
    changes: dict[str, Any],
    actor: str | None = None,
) -> AuditEntry:
    """Log a source update event.

    Args:
        service: AuditService instance
        source_guid: GUID of the updated source
        group_guid: GUID of the group
        changes: Dictionary of field changes
        actor: User/system updating source

    Returns:
        The created AuditEntry
    """
    return service.log_event(
        event_type=AuditEventType.SOURCE_UPDATE,
        resource_guid=source_guid,
        resource_type="source",
        actor=actor,
        group_guid=group_guid,
        details={"changes": changes},
    )


def log_source_delete(
    service: AuditService,
    source_guid: str,
    group_guid: str,
    actor: str | None = None,
) -> AuditEntry:
    """Log a source deletion (soft-delete) event.

    Args:
        service: AuditService instance
        source_guid: GUID of the deleted source
        group_guid: GUID of the group
        actor: User/system deleting source

    Returns:
        The created AuditEntry
    """
    return service.log_event(
        event_type=AuditEventType.SOURCE_DELETE,
        resource_guid=source_guid,
        resource_type="source",
        actor=actor,
        group_guid=group_guid,
    )


def log_document_query(
    service: AuditService,
    query_text: str,
    group_guids: list[str],
    actor: str | None = None,
    result_count: int = 0,
    filters: dict[str, Any] | None = None,
) -> AuditEntry:
    """Log a document query event.

    Args:
        service: AuditService instance
        query_text: The search query text
        group_guids: List of groups queried
        actor: User/system performing query
        result_count: Number of results returned
        filters: Applied query filters

    Returns:
        The created AuditEntry
    """
    details: dict[str, Any] = {
        "query_text": query_text,
        "groups": group_guids,
        "result_count": result_count,
    }
    if filters:
        details["filters"] = filters

    return service.log_event(
        event_type=AuditEventType.DOCUMENT_QUERY,
        resource_type="query",
        actor=actor,
        details=details,
    )
