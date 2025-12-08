"""MCP Query Tools - Phase 8.

Provides MCP tool for document retrieval by GUID.
Full query/search functionality will be added in Phase 12.

Tools:
- get_document: Retrieve a document by its GUID
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

from app.services.document_store import DocumentNotFoundError, DocumentStore

if TYPE_CHECKING:
    pass

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def register_query_tools(mcp: FastMCP, document_store: DocumentStore) -> None:
    """Register query tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        document_store: DocumentStore for document retrieval
    """

    @mcp.tool(
        name="get_document",
        description="Retrieve a document from the repository by its GUID. "
        "Returns the full document content and metadata.",
    )
    def get_document(
        guid: str,
        group_guid: str,
        date_hint: str | None = None,
    ) -> ToolResponse:
        """Get a document by its GUID.

        Args:
            guid: The document GUID to retrieve
            group_guid: The group GUID (required for access control and path resolution)
            date_hint: Optional date hint in YYYY-MM-DD format to speed up lookup.
                      If not provided, all date partitions will be searched.

        Returns:
            JSON response with full document data including:
            - guid: Document unique identifier
            - source_guid: Source that produced this document
            - group_guid: Owning group
            - title: Document title
            - content: Full document content
            - language: Document language code
            - language_detected: Whether language was auto-detected
            - word_count: Number of words
            - version: Document version number
            - duplicate_of: If duplicate, the original document GUID
            - duplicate_score: Similarity score if duplicate
            - created_at: Creation timestamp
            - updated_at: Last update timestamp
            - metadata: Additional document metadata

        Errors:
            - DOCUMENT_NOT_FOUND: The document doesn't exist or isn't accessible
        """
        try:
            # Parse date hint if provided
            date_obj: datetime | None = None
            if date_hint:
                try:
                    parsed_date = date.fromisoformat(date_hint)
                    # Convert date to datetime for the API
                    date_obj = datetime.combine(parsed_date, datetime.min.time())
                except ValueError:
                    return error_response(
                        error_code="INVALID_DATE",
                        message=f"Invalid date format: {date_hint}",
                        recovery_strategy="Use YYYY-MM-DD format for date_hint (e.g., '2025-12-08').",
                    )

            # Load document
            doc = document_store.load(guid, group_guid, date=date_obj)

            # Format full document response
            doc_data = {
                "guid": doc.guid,
                "source_guid": doc.source_guid,
                "group_guid": doc.group_guid,
                "title": doc.title,
                "content": doc.content,
                "language": doc.language,
                "language_detected": doc.language_detected,
                "word_count": doc.word_count,
                "version": doc.version,
                "duplicate_of": doc.duplicate_of,
                "duplicate_score": doc.duplicate_score,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "metadata": doc.metadata,
            }

            return success_response(data=doc_data)

        except DocumentNotFoundError:
            return error_response(
                error_code="DOCUMENT_NOT_FOUND",
                message=f"Document not found: {guid}",
                recovery_strategy="Verify the GUID is correct and you have access to the group. "
                "Provide a date_hint if you know the document's creation date.",
            )

        except Exception as e:
            return error_response(
                error_code="GET_DOCUMENT_ERROR",
                message=f"Failed to retrieve document: {e!s}",
                recovery_strategy="Check the GUID format and try again.",
            )
