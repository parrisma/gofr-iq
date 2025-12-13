"""MCP Ingest Tools.

Provides document ingestion into the APAC brokerage news repository.
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
    """Register ingest tools with the MCP server."""

    @mcp.tool(
        name="ingest_document",
        description=(
            "Add a news article to the repository. "
            "Use when you have news content to store. "
            "Automatically detects language and checks for duplicates."
        ),
    )
    def ingest_document(
        title: str,
        content: str,
        source_guid: str,
        group_guid: str,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResponse:
        """Ingest a news document.

        Args:
            title: Article headline
            content: Full article text
            source_guid: Source identifier (use list_sources to find valid sources)
            group_guid: Group this document belongs to
            language: Language code (en/zh/ja) - auto-detected if omitted
            metadata: Optional extra attributes

        Returns:
            guid: Assigned document ID
            status: "success" or "duplicate"
            language: Detected/provided language
            word_count: Document length
            duplicate_of: Original document ID if duplicate
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
