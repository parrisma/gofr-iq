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
from app.services.group_service import resolve_permitted_groups, resolve_write_group
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
            "Store a news article in the repository. "
            "WORKFLOW: list_sources → ingest_document → query_documents to retrieve. "
            "PREREQUISITES: Must call list_sources first to get valid source_guid. "
            "INPUT FROM: list_sources (source_guid parameter) | create_source (if new source). "
            "OUTPUT TO: query_documents (searches documents) | get_client_feed (filtered by client). "
            "REQUIRES AUTH: Must have a valid token. "
            "AUTO-DETECTS: Language (en/zh/ja) and duplicates. "
            "RETURNS: document_guid, status (success/duplicate), language, word_count."
        ),
    )
    def ingest_document(
        title: Annotated[str, Field(
            min_length=1,
            max_length=500,
            description="Article headline/title",
            examples=["Tech stocks surge on AI optimism", "央行宣布降息"],
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
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
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
            # Get write group from explicit tokens or context header
            # Anonymous users cannot write - they get None
            group_guid = resolve_write_group(auth_tokens=auth_tokens)
            
            if group_guid is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required for document ingestion",
                    recovery_strategy="Pass auth_tokens parameter or include Authorization header with Bearer token.",
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
                recovery_strategy="Call list_sources to find valid source GUIDs, or create_source to register a new one.",
            )

        except WordCountError as e:
            return error_response(
                error_code="WORD_COUNT_EXCEEDED",
                message=str(e),
                recovery_strategy="Reduce content to under 20,000 words or split into multiple documents. Use validate_document to check first.",
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
                recovery_strategy="Run health_check to verify ChromaDB/Neo4j. Use validate_document to check document first.",
            )

        except Exception as e:
            return error_response(
                error_code="INGEST_INTERNAL_ERROR",
                message=f"Unexpected error during ingestion: {e!s}",
                recovery_strategy="Run health_check to verify all services. Check input parameters. Retry if transient.",
            )

    @mcp.tool(
        name="validate_document",
        description=(
            "Validate a document before ingestion (dry-run). "
            "WORKFLOW: validate_document → review issues → ingest_document (if valid). "
            "USE BEFORE: ingest_document to check for issues. "
            "CHECKS: Source validity, word count, language detection, duplicates. "
            "INPUT FROM: list_sources | create_source (source_guid parameter). "
            "OUTPUT TO: ingest_document with same parameters if validation passes. "
            "NO STORAGE: Does not store or index the document. "
            "RETURNS: Validation results including language, word_count, duplicate check."
        ),
    )
    def validate_document(
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
            description="UUID of the source to validate against",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        language: Annotated[str | None, Field(
            default=None,
            min_length=2,
            max_length=5,
            description="ISO 639-1 language code (en/zh/ja) - auto-detected if omitted",
            examples=["en", "zh", "ja"],
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Validate a document without ingesting it.

        Performs all validation checks that ingest_document would perform,
        but does not store, embed, or index the document. Use this to
        pre-flight check documents before bulk ingestion.

        Validation checks performed:
        1. Source existence and access permissions
        2. Word count within limits (max 20,000)
        3. Language detection (if not provided)
        4. Duplicate detection against existing documents

        Args:
            title: Article headline to validate
            content: Full article text to validate
            source_guid: Source UUID to validate against
            language: Language code (optional, auto-detected if omitted)
            auth_tokens: JWT tokens for authentication

        Returns:
            valid: True if document passes all checks
            source_valid: True if source exists and is accessible
            word_count: Document word count
            word_count_valid: True if within limits
            language: Detected or provided language
            language_confidence: Detection confidence (1.0 if provided)
            is_duplicate: True if document appears to be a duplicate
            duplicate_of: GUID of original document if duplicate
            duplicate_score: Similarity score if duplicate
            issues: List of validation issues (empty if valid)

        Errors:
            - AUTH_REQUIRED: No valid authentication token provided
        """
        try:
            from app.services.language_detector import APAC_LANGUAGES
            from app.services.source_registry import SourceNotFoundError

            # Get permitted groups for source access check
            access_groups = resolve_permitted_groups(auth_tokens=auth_tokens)

            # Validate write access (anonymous cannot validate for ingest)
            write_group = resolve_write_group(auth_tokens=auth_tokens)
            if write_group is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required to validate documents",
                    recovery_strategy="Pass auth_tokens parameter or include Authorization header with Bearer token.",
                )

            issues: list[str] = []
            validation_result: dict[str, Any] = {
                "valid": True,
                "source_valid": False,
                "word_count": 0,
                "word_count_valid": False,
                "language": None,
                "language_confidence": 0.0,
                "is_duplicate": False,
                "duplicate_of": None,
                "duplicate_score": None,
                "issues": [],
            }

            # Step 1: Validate source
            try:
                source = ingest_service.source_registry.get(
                    source_guid, access_groups=access_groups
                )
                if source is not None:
                    validation_result["source_valid"] = True
                    validation_result["source_name"] = source.name
                else:
                    issues.append(f"Source not found: {source_guid}")
            except SourceNotFoundError:
                issues.append(f"Source not found: {source_guid}")

            # Step 2: Validate word count
            from app.services.ingest_service import count_words

            word_count = count_words(content)
            validation_result["word_count"] = word_count
            max_word_count = ingest_service.max_word_count

            if word_count <= max_word_count:
                validation_result["word_count_valid"] = True
            else:
                issues.append(
                    f"Word count exceeds limit: {word_count} > {max_word_count}"
                )

            # Step 3: Detect language
            if language:
                validation_result["language"] = language
                validation_result["language_confidence"] = 1.0
                validation_result["language_provided"] = True
                validation_result["is_apac"] = language in APAC_LANGUAGES
            else:
                lang_result = ingest_service.language_detector.detect(
                    f"{title} {content}"
                )
                validation_result["language"] = lang_result.language
                validation_result["language_confidence"] = lang_result.confidence
                validation_result["language_provided"] = False
                validation_result["is_apac"] = lang_result.is_apac

            # Step 4: Check for duplicates
            dup_result = ingest_service.duplicate_detector.check(title, content)
            validation_result["is_duplicate"] = dup_result.is_duplicate
            if dup_result.is_duplicate:
                validation_result["duplicate_of"] = dup_result.duplicate_of
                validation_result["duplicate_score"] = dup_result.score
                # Duplicates are not an error, just a warning
                issues.append(
                    f"Document appears to be duplicate of: {dup_result.duplicate_of}"
                )

            # Set overall validity
            validation_result["issues"] = issues
            validation_result["valid"] = (
                validation_result["source_valid"]
                and validation_result["word_count_valid"]
            )

            return success_response(
                data=validation_result,
                message="Validation passed" if validation_result["valid"] else "Validation failed",
            )

        except ValidationError as e:
            return error_response(
                error_code="VALIDATION_ERROR",
                message="Invalid input parameters",
                recovery_strategy="Ensure title (1-500 chars), content (10+ chars), source_guid (UUID) are provided.",
                details={"errors": e.errors()},
            )

        except Exception as e:
            return error_response(
                error_code="VALIDATION_CHECK_FAILED",
                message=f"Unexpected error during validation: {e!s}",
                recovery_strategy="Run health_check to verify services. Check input parameters.",
            )
