"""MCP Ingest Tools - Phase 8.

Provides MCP tool for document ingestion into the news repository.

Tool:
- ingest_document: Ingest a new document with validation, language detection, and duplicate checking
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent
from pydantic import ValidationError

from app.services.ingest_service import (
    IngestError,
    IngestService,
    SourceValidationError,
    WordCountError,
)

if TYPE_CHECKING:
    pass

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def register_ingest_tools(mcp: FastMCP, ingest_service: IngestService) -> None:
    """Register ingest tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        ingest_service: IngestService for document ingestion
    """

    @mcp.tool(
        name="ingest_document",
        description="Ingest a news document into the repository. "
        "Validates source, detects language, checks for duplicates, and stores the document.",
    )
    def ingest_document(
        title: str,
        content: str,
        source_guid: str,
        group_guid: str,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResponse:
        """Ingest a document into the news repository.

        Args:
            title: Document title (required, non-empty)
            content: Document content (required, non-empty)
            source_guid: GUID of the registered source (required, valid UUID)
            group_guid: GUID of the group this document belongs to (required, valid UUID)
            language: Optional language code (e.g., 'en', 'zh', 'ja'). Auto-detected if not provided.
            metadata: Optional metadata dictionary for additional document attributes

        Returns:
            JSON response with ingestion result including:
            - guid: The assigned document GUID
            - status: "success" or "duplicate"
            - language: The document language
            - language_detected: Whether language was auto-detected
            - word_count: Number of words in the document
            - duplicate_of: If duplicate, the GUID of the original document

        Errors:
            - INVALID_SOURCE: The source_guid doesn't exist or isn't accessible
            - WORD_COUNT_EXCEEDED: Document exceeds the maximum word count limit
            - VALIDATION_ERROR: Invalid input parameters
            - INGEST_ERROR: General ingestion failure
        """
        try:
            result = ingest_service.ingest(
                title=title,
                content=content,
                source_guid=source_guid,
                group_guid=group_guid,
                language=language,
                metadata=metadata,
            )

            return success_response(
                data=result.to_dict(),
                message="Document ingested successfully"
                if result.status.value == "success"
                else "Document flagged as duplicate",
            )

        except SourceValidationError as e:
            return error_response(
                error_code="INVALID_SOURCE",
                message=str(e),
                recovery_strategy="Verify the source_guid exists and you have access to it. "
                "Use list_sources to see available sources.",
            )

        except WordCountError as e:
            return error_response(
                error_code="WORD_COUNT_EXCEEDED",
                message=str(e),
                recovery_strategy="Reduce the document content length or split into multiple documents.",
            )

        except ValidationError as e:
            return error_response(
                error_code="VALIDATION_ERROR",
                message="Invalid input parameters",
                recovery_strategy="Check that all required fields are provided with valid values.",
                details={"errors": e.errors()},
            )

        except IngestError as e:
            return error_response(
                error_code="INGEST_ERROR",
                message=str(e),
                recovery_strategy="Check the error message and retry the operation.",
            )

        except Exception as e:
            return error_response(
                error_code="INTERNAL_ERROR",
                message=f"Unexpected error during ingestion: {e!s}",
                recovery_strategy="Contact support if the issue persists.",
            )
