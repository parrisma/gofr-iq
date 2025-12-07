"""Source Registry for APAC Brokerage News Repository.

This module provides storage and management for news sources with:
- CRUD operations (create, read, update, soft-delete)
- Group-based access control
- Audit logging for changes
- Region and type filtering
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.models import Source, SourceMetadata, SourceType, TrustLevel


class SourceNotFoundError(Exception):
    """Raised when a source is not found."""

    def __init__(self, guid: str) -> None:
        self.guid = guid
        super().__init__(f"Source not found: {guid}")


class SourceAccessDeniedError(Exception):
    """Raised when access to a source is denied."""

    def __init__(self, guid: str, group_guid: str) -> None:
        self.guid = guid
        self.group_guid = group_guid
        super().__init__(f"Access denied to source {guid} for group {group_guid}")


class SourceRegistryError(Exception):
    """Base exception for source registry errors."""

    pass


class AuditEntry:
    """Represents an audit log entry for source changes."""

    def __init__(
        self,
        source_guid: str,
        action: str,
        timestamp: datetime,
        changes: dict[str, Any] | None = None,
        actor_group: str | None = None,
    ) -> None:
        self.source_guid = source_guid
        self.action = action
        self.timestamp = timestamp
        self.changes = changes or {}
        self.actor_group = actor_group

    def to_dict(self) -> dict[str, Any]:
        """Convert audit entry to dictionary."""
        return {
            "source_guid": self.source_guid,
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
            "changes": self.changes,
            "actor_group": self.actor_group,
        }


class SourceRegistry:
    """File-based source registry with group-based access control.

    Sources are stored in a directory structure:
        {base_path}/sources/{group_guid}/{source_guid}.json

    Audit logs are stored in:
        {base_path}/audit/sources/{source_guid}.jsonl

    Attributes:
        base_path: Root path for all source storage
    """

    def __init__(self, base_path: str | Path) -> None:
        """Initialize the source registry.

        Args:
            base_path: Root directory for source storage
        """
        self.base_path = Path(base_path)
        self._sources_path = self.base_path / "sources"
        self._audit_path = self.base_path / "audit" / "sources"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Ensure base directories exist."""
        self._sources_path.mkdir(parents=True, exist_ok=True)
        self._audit_path.mkdir(parents=True, exist_ok=True)

    def _get_source_path(self, source_guid: str, group_guid: str) -> Path:
        """Get the file path for a source.

        Args:
            source_guid: Source GUID
            group_guid: Group GUID

        Returns:
            Full path to the source file
        """
        return self._sources_path / group_guid / f"{source_guid}.json"

    def _get_group_path(self, group_guid: str) -> Path:
        """Get the path for a group's sources.

        Args:
            group_guid: Group GUID

        Returns:
            Path to the group's source directory
        """
        return self._sources_path / group_guid

    def _get_audit_path(self, source_guid: str) -> Path:
        """Get the path for a source's audit log.

        Args:
            source_guid: Source GUID

        Returns:
            Path to the audit log file
        """
        return self._audit_path / f"{source_guid}.jsonl"

    def _write_audit_entry(
        self,
        source_guid: str,
        action: str,
        changes: dict[str, Any] | None = None,
        actor_group: str | None = None,
    ) -> None:
        """Write an audit log entry.

        Args:
            source_guid: Source being audited
            action: Action performed (create, update, delete)
            changes: Dictionary of changed fields
            actor_group: Group performing the action
        """
        entry = AuditEntry(
            source_guid=source_guid,
            action=action,
            timestamp=datetime.utcnow(),
            changes=changes,
            actor_group=actor_group,
        )
        audit_path = self._get_audit_path(source_guid)
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    def create(
        self,
        name: str,
        group_guid: str,
        source_type: SourceType = SourceType.OTHER,
        region: str | None = None,
        languages: list[str] | None = None,
        trust_level: TrustLevel = TrustLevel.UNVERIFIED,
        metadata: SourceMetadata | dict[str, Any] | None = None,
    ) -> Source:
        """Create a new source.

        Args:
            name: Human-readable source name
            group_guid: Group this source belongs to
            source_type: Type of source
            region: Geographic region coverage
            languages: Languages this source provides
            trust_level: Credibility level
            metadata: Optional additional metadata

        Returns:
            The created Source

        Raises:
            SourceRegistryError: If creation fails
        """
        try:
            source_guid = str(uuid4())

            # Handle metadata conversion
            if isinstance(metadata, dict):
                metadata = SourceMetadata(**metadata)

            source = Source(
                source_guid=source_guid,
                group_guid=group_guid,
                name=name,
                type=source_type,
                region=region,
                languages=languages or ["en"],
                trust_level=trust_level,
                metadata=metadata,
            )

            # Save the source
            file_path = self._get_source_path(source_guid, group_guid)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            data = source.model_dump(mode="json")
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Write audit entry
            self._write_audit_entry(
                source_guid=source_guid,
                action="create",
                changes={"initial": data},
                actor_group=group_guid,
            )

            return source
        except Exception as e:
            raise SourceRegistryError(f"Failed to create source: {e}") from e

    def get(
        self,
        source_guid: str,
        access_groups: list[str] | None = None,
    ) -> Source:
        """Get a source by GUID.

        Args:
            source_guid: Source GUID to retrieve
            access_groups: Optional list of group GUIDs the caller has access to.
                          If provided, the source must belong to one of these groups.

        Returns:
            The Source

        Raises:
            SourceNotFoundError: If source doesn't exist
            SourceAccessDeniedError: If access_groups provided and source's group not in list
            SourceRegistryError: If load fails
        """
        try:
            # Always search all groups first to find the source
            all_groups = self._list_all_groups()

            for group_guid in all_groups:
                file_path = self._get_source_path(source_guid, group_guid)
                if file_path.exists():
                    source = self._load_from_path(file_path)
                    # If access_groups specified, verify access
                    if access_groups and source.group_guid not in access_groups:
                        raise SourceAccessDeniedError(source_guid, source.group_guid)
                    return source

            raise SourceNotFoundError(source_guid)
        except (SourceNotFoundError, SourceAccessDeniedError):
            raise
        except Exception as e:
            raise SourceRegistryError(f"Failed to get source {source_guid}: {e}") from e

    def _load_from_path(self, file_path: Path) -> Source:
        """Load a source from a specific path.

        Args:
            file_path: Path to the source file

        Returns:
            The loaded Source
        """
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return Source(**data)

    def _list_all_groups(self) -> list[str]:
        """List all group GUIDs that have sources.

        Returns:
            List of group GUIDs
        """
        if not self._sources_path.exists():
            return []
        return [
            d.name for d in self._sources_path.iterdir() if d.is_dir()
        ]

    def list_sources(
        self,
        group_guid: str | None = None,
        access_groups: list[str] | None = None,
        region: str | None = None,
        source_type: SourceType | None = None,
        include_inactive: bool = False,
    ) -> list[Source]:
        """List sources with optional filters.

        Args:
            group_guid: Filter by specific group
            access_groups: Limit to sources in these groups
            region: Filter by region
            source_type: Filter by source type
            include_inactive: Include soft-deleted sources

        Returns:
            List of matching Sources
        """
        sources: list[Source] = []

        # Determine which groups to search
        if group_guid:
            groups_to_search = [group_guid]
        elif access_groups:
            groups_to_search = access_groups
        else:
            groups_to_search = self._list_all_groups()

        for grp in groups_to_search:
            group_path = self._get_group_path(grp)
            if not group_path.exists():
                continue

            for source_file in group_path.glob("*.json"):
                try:
                    source = self._load_from_path(source_file)

                    # Apply filters
                    if not include_inactive and not source.active:
                        continue
                    if region and source.region != region:
                        continue
                    if source_type and source.type != source_type:
                        continue

                    sources.append(source)
                except Exception:
                    # Skip invalid source files
                    continue

        return sources

    def update(
        self,
        source_guid: str,
        access_groups: list[str] | None = None,
        name: str | None = None,
        source_type: SourceType | None = None,
        region: str | None = None,
        languages: list[str] | None = None,
        trust_level: TrustLevel | None = None,
        metadata: SourceMetadata | dict[str, Any] | None = None,
    ) -> Source:
        """Update an existing source.

        Args:
            source_guid: Source to update
            access_groups: Groups the caller has access to (for authorization)
            name: New name (optional)
            source_type: New type (optional)
            region: New region (optional)
            languages: New languages (optional)
            trust_level: New trust level (optional)
            metadata: New metadata (optional)

        Returns:
            The updated Source

        Raises:
            SourceNotFoundError: If source doesn't exist
            SourceAccessDeniedError: If caller doesn't have access
            SourceRegistryError: If update fails
        """
        try:
            # Get the existing source
            source = self.get(source_guid, access_groups)

            # Track changes for audit
            changes: dict[str, Any] = {}

            # Apply updates
            if name is not None and name != source.name:
                changes["name"] = {"old": source.name, "new": name}
                source.name = name

            if source_type is not None and source_type != source.type:
                changes["type"] = {"old": source.type.value, "new": source_type.value}
                source.type = source_type

            if region is not None and region != source.region:
                changes["region"] = {"old": source.region, "new": region}
                source.region = region

            if languages is not None and languages != source.languages:
                changes["languages"] = {"old": source.languages, "new": languages}
                source.languages = languages

            if trust_level is not None and trust_level != source.trust_level:
                changes["trust_level"] = {
                    "old": source.trust_level.value,
                    "new": trust_level.value,
                }
                source.trust_level = trust_level

            if metadata is not None:
                if isinstance(metadata, dict):
                    metadata = SourceMetadata(**metadata)
                old_meta = source.metadata.model_dump() if source.metadata else None
                changes["metadata"] = {"old": old_meta, "new": metadata.model_dump()}
                source.metadata = metadata

            # Update timestamp
            source.updated_at = datetime.utcnow()

            # Save the updated source
            file_path = self._get_source_path(source_guid, source.group_guid)
            data = source.model_dump(mode="json")
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Write audit entry if there were changes
            if changes:
                self._write_audit_entry(
                    source_guid=source_guid,
                    action="update",
                    changes=changes,
                    actor_group=access_groups[0] if access_groups else None,
                )

            return source
        except (SourceNotFoundError, SourceAccessDeniedError):
            raise
        except Exception as e:
            raise SourceRegistryError(f"Failed to update source {source_guid}: {e}") from e

    def soft_delete(
        self,
        source_guid: str,
        access_groups: list[str] | None = None,
    ) -> Source:
        """Soft-delete a source by marking it inactive.

        Args:
            source_guid: Source to delete
            access_groups: Groups the caller has access to

        Returns:
            The deactivated Source

        Raises:
            SourceNotFoundError: If source doesn't exist
            SourceAccessDeniedError: If caller doesn't have access
            SourceRegistryError: If delete fails
        """
        try:
            # Get the existing source
            source = self.get(source_guid, access_groups)

            # Deactivate
            was_active = source.active
            source.deactivate()

            # Save the updated source
            file_path = self._get_source_path(source_guid, source.group_guid)
            data = source.model_dump(mode="json")
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Write audit entry
            self._write_audit_entry(
                source_guid=source_guid,
                action="soft_delete",
                changes={"active": {"old": was_active, "new": False}},
                actor_group=access_groups[0] if access_groups else None,
            )

            return source
        except (SourceNotFoundError, SourceAccessDeniedError):
            raise
        except Exception as e:
            raise SourceRegistryError(f"Failed to soft-delete source {source_guid}: {e}") from e

    def exists(self, source_guid: str, group_guid: str | None = None) -> bool:
        """Check if a source exists.

        Args:
            source_guid: Source GUID
            group_guid: Optional group to check in

        Returns:
            True if source exists
        """
        try:
            if group_guid:
                file_path = self._get_source_path(source_guid, group_guid)
                return file_path.exists()
            else:
                self.get(source_guid)
                return True
        except SourceNotFoundError:
            return False

    def get_audit_log(self, source_guid: str) -> list[dict[str, Any]]:
        """Get the audit log for a source.

        Args:
            source_guid: Source GUID

        Returns:
            List of audit entries (newest first)
        """
        audit_path = self._get_audit_path(source_guid)
        if not audit_path.exists():
            return []

        entries: list[dict[str, Any]] = []
        with audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        # Return newest first
        return list(reversed(entries))

    def count_sources(
        self,
        group_guid: str | None = None,
        include_inactive: bool = False,
    ) -> int:
        """Count sources matching criteria.

        Args:
            group_guid: Optional group to filter by
            include_inactive: Include soft-deleted sources

        Returns:
            Count of matching sources
        """
        return len(self.list_sources(
            group_guid=group_guid,
            include_inactive=include_inactive,
        ))
