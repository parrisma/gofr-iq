"""MCP Ingest Tools.

Provides document ingestion into the APAC brokerage news repository.

Group Access Control:
    - Documents are written to the group associated with the authenticated token
    - Anonymous users cannot ingest documents (requires authentication)
    - The group is extracted from the JWT token, not from client parameters
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, ValidationError

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent
from app.services.group_service import get_write_group_from_context
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
            "Automatically detects language and checks for duplicates. "
            "Requires authentication - documents are stored in your token's group."
        ),
    )
    def ingest_document(
        title: Annotated[str, Field(
            min_length=1,
            max_length=500,
            description="Article headline/title",
        )],
        content: Annotated[str, Field(
            min_length=10,
            description="Full article text content",
        )],
        source_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the source (use list_sources to find valid sources)",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        language: Annotated[str | None, Field(
            default=None,
            min_length=2,
            max_length=5,
            description="ISO 639-1 language code (en/zh/ja) - auto-detected if omitted",
            examples=["en", "zh", "ja"],
        )] = None,
        metadata: Annotated[dict[str, Any] | None, Field(
            default=None,
            description="Optional extra attributes as key-value pairs",
        )] = None,
    ) -> ToolResponse:
        """Ingest a news document.

        The document is automatically stored in the group associated with
        your authentication token. The group is a string identifier like
        'reuters-feed' or 'sales-team-nyc', not a UUID.
        Anonymous users cannot ingest documents.

        Args:
            title: Article headline
            content: Full article text
            source_guid: Source UUID (use list_sources to find valid sources)
            language: Language code (en/zh/ja) - auto-detected if omitted
            metadata: Optional extra attributes

        Returns:
            guid: Assigned document ID
            status: "success" or "duplicate"
            language: Detected/provided language
            word_count: Document length
            duplicate_of: Original document ID if duplicate
            group_guid: Group name/identifier (string like 'reuters-feed')
        """
        try:
            # Get write group from authentication context
            # Anonymous users cannot write - they get None
            group_guid = get_write_group_from_context()
            
            if group_guid is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required for document ingestion",
                    recovery_strategy="Provide a valid Bearer token in the Authorization header.",
                )

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
