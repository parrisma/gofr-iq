"""Canonical Document Store for APAC Brokerage News Repository.

This module provides file-based storage for documents with:
- GUID-based naming
- Group partitioning
- Date-based subdirectories
- Document versioning support
- Group-based access control
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models import Document, DocumentCreate, count_words


class DocumentNotFoundError(Exception):
    """Raised when a document is not found."""

    def __init__(self, guid: str, group_guid: str | None = None) -> None:
        self.guid = guid
        self.group_guid = group_guid
        msg = f"Document not found: {guid}"
        if group_guid:
            msg += f" in group {group_guid}"
        super().__init__(msg)


class DocumentAccessDeniedError(Exception):
    """Raised when access to a document is denied due to group restrictions."""

    def __init__(self, guid: str, group_guid: str, permitted_groups: list[str]) -> None:
        self.guid = guid
        self.group_guid = group_guid
        self.permitted_groups = permitted_groups
        super().__init__(
            f"Access denied: document {guid} belongs to group '{group_guid}', "
            f"not in permitted groups {permitted_groups}"
        )


class DocumentStoreError(Exception):
    """Base exception for document store errors."""

    pass


class DocumentStore:
    """File-based document storage with group partitioning.

    Documents are stored in a directory structure:
        {base_path}/documents/{group_guid}/{YYYY-MM-DD}/{guid}.json

    Attributes:
        base_path: Root path for all document storage
    """

    def __init__(self, base_path: str | Path) -> None:
        """Initialize the document store.

        Args:
            base_path: Root directory for document storage
        """
        self.base_path = Path(base_path)
        self._documents_path = self.base_path / "documents"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Ensure base directories exist."""
        self._documents_path.mkdir(parents=True, exist_ok=True)

    def _get_document_path(
        self, guid: str, group_guid: str, created_at: datetime
    ) -> Path:
        """Get the file path for a document.

        Args:
            guid: Document GUID
            group_guid: Group GUID
            created_at: Document creation timestamp

        Returns:
            Full path to the document file
        """
        date_str = created_at.strftime("%Y-%m-%d")
        return self._documents_path / group_guid / date_str / f"{guid}.json"

    def _get_group_path(self, group_guid: str) -> Path:
        """Get the path for a group's documents.

        Args:
            group_guid: Group GUID

        Returns:
            Path to the group's document directory
        """
        return self._documents_path / group_guid

    def save(self, document: Document) -> Path:
        """Save a document to the store.

        Creates the necessary directory structure and writes the document
        as JSON.

        Args:
            document: Document to save

        Returns:
            Path where the document was saved

        Raises:
            DocumentStoreError: If save fails
        """
        try:
            file_path = self._get_document_path(
                document.guid, document.group_guid, document.created_at
            )
            file_path.parent.mkdir(parents=True, exist_ok=True)

            data = document.model_dump(mode="json")
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return file_path
        except Exception as e:
            raise DocumentStoreError(f"Failed to save document {document.guid}: {e}") from e

    def load(self, guid: str, group_guid: str, date: datetime | str | None = None) -> Document:
        """Load a document from the store.

        Args:
            guid: Document GUID
            group_guid: Group GUID
            date: Optional date to narrow search (YYYY-MM-DD string or datetime)

        Returns:
            The loaded Document

        Raises:
            DocumentNotFoundError: If document doesn't exist
            DocumentStoreError: If load fails
        """
        try:
            # If date provided, try direct path
            if date is not None:
                if isinstance(date, datetime):
                    date_str = date.strftime("%Y-%m-%d")
                else:
                    date_str = date
                file_path = self._documents_path / group_guid / date_str / f"{guid}.json"
                if file_path.exists():
                    return self._load_from_path(file_path)

            # Otherwise, search all date directories in the group
            group_path = self._get_group_path(group_guid)
            if not group_path.exists():
                raise DocumentNotFoundError(guid, group_guid)

            for date_dir in group_path.iterdir():
                if date_dir.is_dir():
                    file_path = date_dir / f"{guid}.json"
                    if file_path.exists():
                        return self._load_from_path(file_path)

            raise DocumentNotFoundError(guid, group_guid)
        except DocumentNotFoundError:
            raise
        except Exception as e:
            raise DocumentStoreError(f"Failed to load document {guid}: {e}") from e

    def load_with_access_check(
        self,
        guid: str,
        permitted_groups: list[str],
        date: datetime | str | None = None,
    ) -> Document:
        """Load a document with group access validation.
        
        Searches for the document across all permitted groups and validates
        that the document belongs to one of them.

        Args:
            guid: Document GUID
            permitted_groups: List of group GUIDs the user can access
            date: Optional date to narrow search (YYYY-MM-DD string or datetime)

        Returns:
            The loaded Document

        Raises:
            DocumentNotFoundError: If document doesn't exist in any permitted group
            DocumentAccessDeniedError: If document exists but user lacks access
            DocumentStoreError: If load fails
        """
        # Try each permitted group
        for group_guid in permitted_groups:
            try:
                doc = self.load(guid, group_guid, date)
                return doc
            except DocumentNotFoundError:
                continue
        
        # Document not found in any permitted group
        # Check if it exists in another group (for better error message)
        for group_dir in self._documents_path.iterdir():
            if group_dir.is_dir() and group_dir.name not in permitted_groups:
                for date_dir in group_dir.iterdir():
                    if date_dir.is_dir():
                        file_path = date_dir / f"{guid}.json"
                        if file_path.exists():
                            raise DocumentAccessDeniedError(
                                guid=guid,
                                group_guid=group_dir.name,
                                permitted_groups=permitted_groups,
                            )
        
        raise DocumentNotFoundError(guid, None)

    def list_by_permitted_groups(
        self,
        permitted_groups: list[str],
        date: datetime | str | None = None,
        limit: int | None = None,
    ) -> list[Document]:
        """List documents from all permitted groups.

        Args:
            permitted_groups: List of group GUIDs to include
            date: Optional date filter (YYYY-MM-DD)
            limit: Maximum number of documents to return

        Returns:
            List of documents from all permitted groups, sorted by created_at desc
        """
        documents: list[Document] = []
        
        for group_guid in permitted_groups:
            group_docs = self.list_by_group(group_guid, date, limit=None)
            documents.extend(group_docs)
        
        # Sort by created_at descending
        documents.sort(key=lambda d: d.created_at, reverse=True)
        
        if limit:
            documents = documents[:limit]
        
        return documents

    def _load_from_path(self, file_path: Path) -> Document:
        """Load a document from a specific path.

        Args:
            file_path: Path to the document file

        Returns:
            The loaded Document
        """
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return Document(**data)

    def exists(self, guid: str, group_guid: str, date: datetime | str | None = None) -> bool:
        """Check if a document exists.

        Args:
            guid: Document GUID
            group_guid: Group GUID
            date: Optional date to narrow search

        Returns:
            True if document exists
        """
        try:
            self.load(guid, group_guid, date)
            return True
        except DocumentNotFoundError:
            return False

    def delete(self, guid: str, group_guid: str, date: datetime | str | None = None) -> bool:
        """Delete a document from the store.

        Note: This is a hard delete. For soft-delete, mark document as inactive.

        Args:
            guid: Document GUID
            group_guid: Group GUID
            date: Optional date to narrow search

        Returns:
            True if document was deleted, False if not found
        """
        try:
            # Find the document first
            doc = self.load(guid, group_guid, date)
            file_path = self._get_document_path(
                doc.guid, doc.group_guid, doc.created_at
            )
            file_path.unlink()
            return True
        except DocumentNotFoundError:
            return False

    def create_from_input(
        self,
        create_input: DocumentCreate,
        language: str | None = None,
        language_detected: bool = False,
    ) -> Document:
        """Create and save a document from input data.

        Args:
            create_input: Document creation input
            language: Detected or provided language
            language_detected: Whether language was auto-detected

        Returns:
            The created and saved Document
        """
        doc = Document(
            source_guid=create_input.source_guid,
            group_guid=create_input.group_guid,
            title=create_input.title,
            content=create_input.content,
            word_count=count_words(create_input.content),
            language=language or create_input.language or "en",
            language_detected=language_detected,
            metadata=create_input.metadata,
        )
        self.save(doc)
        return doc

    def save_version(self, original: Document, update_data: dict[str, Any]) -> Document:
        """Create and save a new version of a document.

        Args:
            original: Original document to version
            update_data: Fields to update (title, content, metadata)

        Returns:
            The new version Document
        """
        new_version = original.create_new_version(
            title=update_data.get("title"),
            content=update_data.get("content"),
            metadata=update_data.get("metadata"),
        )
        self.save(new_version)
        return new_version

    def list_by_group(
        self,
        group_guid: str,
        date: datetime | str | None = None,
        limit: int | None = None,
    ) -> list[Document]:
        """List documents in a group.

        Args:
            group_guid: Group GUID
            date: Optional date filter (YYYY-MM-DD)
            limit: Maximum number of documents to return

        Returns:
            List of documents in the group
        """
        documents: list[Document] = []
        group_path = self._get_group_path(group_guid)

        if not group_path.exists():
            return documents

        # Filter by date if provided
        if date is not None:
            if isinstance(date, datetime):
                date_str = date.strftime("%Y-%m-%d")
            else:
                date_str = date
            date_dirs = [group_path / date_str]
        else:
            date_dirs = sorted(group_path.iterdir(), reverse=True)

        for date_dir in date_dirs:
            if not date_dir.is_dir():
                continue

            for doc_file in sorted(date_dir.glob("*.json"), reverse=True):
                try:
                    doc = self._load_from_path(doc_file)
                    documents.append(doc)
                    if limit and len(documents) >= limit:
                        return documents
                except Exception:
                    # Skip invalid files
                    continue  # nosec B112

        return documents

    def list_by_date_range(
        self,
        group_guid: str,
        date_from: datetime,
        date_to: datetime,
        limit: int | None = None,
    ) -> list[Document]:
        """List documents in a group within a date range.

        Args:
            group_guid: Group GUID
            date_from: Start date (inclusive)
            date_to: End date (inclusive)
            limit: Maximum number of documents to return

        Returns:
            List of documents in the date range
        """
        documents: list[Document] = []
        group_path = self._get_group_path(group_guid)

        if not group_path.exists():
            return documents

        # Iterate through date directories
        for date_dir in sorted(group_path.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue

            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                # Compare dates only (not times) by using date at midnight
                date_from_date = date_from.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
                date_to_date = date_to.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)
                if dir_date < date_from_date or dir_date > date_to_date:
                    continue
            except ValueError:
                continue

            for doc_file in sorted(date_dir.glob("*.json"), reverse=True):
                try:
                    doc = self._load_from_path(doc_file)
                    documents.append(doc)
                    if limit and len(documents) >= limit:
                        return documents
                except Exception:
                    continue  # nosec B112

        return documents

    def get_version_chain(self, guid: str, group_guid: str) -> list[Document]:
        """Get the full version chain for a document.

        Args:
            guid: Document GUID (any version in chain)
            group_guid: Group GUID

        Returns:
            List of documents in version order (oldest first)
        """
        # Load the starting document
        doc = self.load(guid, group_guid)
        chain: list[Document] = [doc]

        # Walk backward through previous versions
        while doc.previous_version_guid:
            doc = self.load(doc.previous_version_guid, group_guid)
            chain.insert(0, doc)

        return chain

    def get_latest_version(self, guid: str, group_guid: str) -> Document:
        """Get the latest version of a document.

        If guid is for an older version, this searches for newer versions.
        Currently returns the provided document as we don't track forward links.

        Args:
            guid: Document GUID
            group_guid: Group GUID

        Returns:
            The document (currently doesn't search forward)
        """
        # Note: To fully implement this, we'd need to track forward links
        # or scan all documents. For now, return the requested document.
        return self.load(guid, group_guid)

    def count_documents(self, group_guid: str) -> int:
        """Count documents in a group.

        Args:
            group_guid: Group GUID

        Returns:
            Number of documents in the group
        """
        count = 0
        group_path = self._get_group_path(group_guid)

        if not group_path.exists():
            return 0

        for date_dir in group_path.iterdir():
            if date_dir.is_dir():
                count += len(list(date_dir.glob("*.json")))

        return count

    def __repr__(self) -> str:
        return f"DocumentStore(base_path={self.base_path})"
