"""MCP Ingest Tools.

Provides document ingestion into the APAC brokerage news repository.

Group Access Control:
    - Documents are written to the group associated with the authenticated token
    - Anonymous users cannot ingest documents (requires authentication)
    - The group is extracted from the JWT token, not from client parameters
    
Source Access:
    - Sources are global entities (not tied to groups)
    - Any authenticated user can reference any source when ingesting documents
    - Source validation checks only for existence, not group membership
    
Document Deletion:
    - Admin-only operation for complete document removal
    - Removes from document store, embedding index, and graph index
    - Requires explicit confirmation parameter for safety
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, ValidationError

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent
from app.services.document_store import DocumentNotFoundError
from app.services.group_service import (
    AdminAccessDeniedError,
    get_group_uuid_by_name,
    require_admin,
    resolve_permitted_groups,
    resolve_write_group,
)
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
            "WORKFLOW: list_sources -> ingest_document -> query_documents to retrieve. "
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
            # Returns group NAME (e.g., "apac-sales")
            group_name = resolve_write_group(auth_tokens=auth_tokens)
            
            if group_name is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required for document ingestion",
                    recovery_strategy="Pass auth_tokens parameter or include Authorization header with Bearer token.",
                )
            
            # Convert group name to UUID for storage
            group_guid = get_group_uuid_by_name(group_name)
            if group_guid is None:
                return error_response(
                    error_code="INVALID_GROUP",
                    message=f"Group '{group_name}' not found",
                    recovery_strategy="Verify the group exists and your token has access to it.",
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
            "WORKFLOW: validate_document -> review issues -> ingest_document (if valid). "
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

            # Validate write access (anonymous cannot validate for ingest)
            write_group_name = resolve_write_group(auth_tokens=auth_tokens)
            if write_group_name is None:
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

            # Step 1: Validate source (sources are now global, not group-specific)
            try:
                source = ingest_service.source_registry.get(source_guid)
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

    @mcp.tool(
        name="delete_document",
        description=(
            "[ADMIN ONLY] Permanently delete a document and all associated data. "
            "DELETES: Document file, vector embeddings (ChromaDB), graph entries (Neo4j). "
            "WARNING: This is irreversible - no soft-delete or recovery possible. "
            "REQUIRES: Admin group membership and explicit confirm=true. "
            "USE WHEN: Removing test data, GDPR/data deletion requests, corrupted documents. "
            "WORKFLOW: get_document (verify exists) -> delete_document -> confirm deletion. "
            "RETURNS: Confirmation with deletion statistics (files, vectors, graph nodes)."
        ),
    )
    def delete_document(
        document_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the document to delete permanently",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        group_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the group containing the document",
            examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
        )],
        confirm: Annotated[bool, Field(
            description="Must be true to execute deletion (safety check)",
        )],
        date_hint: Annotated[str | None, Field(
            default=None,
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            description="Document creation date in YYYY-MM-DD format to speed up lookup (optional)",
            examples=["2025-12-08", "2026-01-15"],
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (admin required)",
        )] = None,
    ) -> ToolResponse:
        """Permanently delete a document and all associated data.

        This performs a complete hard delete across all three storage layers:
        1. Document file from canonical store
        2. Vector embeddings from ChromaDB
        3. Graph nodes and relationships from Neo4j

        This operation is irreversible. The document and all associated data
        will be permanently removed from the system.

        Args:
            document_guid: UUID of the document to delete
            group_guid: UUID of the group containing the document
            confirm: Must be True to execute (prevents accidental deletion)
            date_hint: Optional date to speed up file lookup
            auth_tokens: JWT tokens (admin group required)

        Returns:
            Confirmation message with deletion statistics:
            - document_guid: The deleted document ID
            - title: Title of the deleted document
            - group_guid: Group that contained the document
            - deleted_from: List of storage layers deleted from
            - vector_chunks_deleted: Number of vector chunks removed

        Errors:
            - AUTH_REQUIRED: No valid authentication token provided
            - ACCESS_DENIED: User not in admin group
            - DOCUMENT_NOT_FOUND: Document doesn't exist in specified group
            - CONFIRMATION_REQUIRED: confirm parameter not set to true
            - DELETION_FAILED: One or more storage layers failed to delete
        """
        try:
            # Require admin access
            try:
                require_admin(auth_tokens=auth_tokens)
            except AdminAccessDeniedError as e:
                return error_response(
                    error_code="ACCESS_DENIED",
                    message=str(e),
                    recovery_strategy="Use a token with 'admin' group membership.",
                )

            # Safety check - require explicit confirmation
            if not confirm:
                return error_response(
                    error_code="CONFIRMATION_REQUIRED",
                    message="Delete operation requires confirm=true parameter to execute",
                    recovery_strategy="Set confirm=true in the request to proceed with deletion. This is a safety check to prevent accidental deletions.",
                )

            # Verify document exists before attempting deletion
            try:
                doc = ingest_service.document_store.load(
                    document_guid, group_guid, date_hint
                )
            except DocumentNotFoundError:
                return error_response(
                    error_code="DOCUMENT_NOT_FOUND",
                    message=f"Document {document_guid} not found in group {group_guid}",
                    recovery_strategy="Verify the document_guid and group_guid are correct. Use get_document to verify the document exists.",
                )

            # Track deletion results
            results: dict[str, Any] = {
                "document_guid": document_guid,
                "title": doc.title,
                "group_guid": group_guid,
                "deleted_from": [],
            }

            # 1. Delete from document store (canonical file)
            file_deleted = ingest_service.document_store.delete(
                document_guid, group_guid, date_hint
            )
            if file_deleted:
                results["deleted_from"].append("document_store")

            # 2. Delete from embedding index (ChromaDB vectors)
            vector_chunks_deleted = 0
            if ingest_service.embedding_index:
                vector_chunks_deleted = ingest_service.embedding_index.delete_document(
                    document_guid
                )
                results["vector_chunks_deleted"] = vector_chunks_deleted
                if vector_chunks_deleted > 0:
                    results["deleted_from"].append(
                        f"embedding_index ({vector_chunks_deleted} chunks)"
                    )

            # 3. Delete from graph index (Neo4j)
            if ingest_service.graph_index:
                from app.services.graph_index import NodeLabel

                graph_deleted = ingest_service.graph_index.delete_node(
                    NodeLabel.DOCUMENT, document_guid
                )
                if graph_deleted:
                    results["deleted_from"].append("graph_index")

            # Log the deletion for audit trail
            if hasattr(ingest_service, 'audit_service'):
                audit_svc = getattr(ingest_service, 'audit_service', None)
                if audit_svc:
                    from app.services.audit_service import log_document_delete

                    # Get actor from token groups
                    groups = resolve_permitted_groups(auth_tokens=auth_tokens)
                    actor = groups[0] if groups else "admin"
                    log_document_delete(
                        audit_svc,
                        document_guid=document_guid,
                        group_guid=group_guid,
                        title=doc.title,
                        actor=actor,
                        deleted_from=results["deleted_from"],
                        vector_chunks_deleted=vector_chunks_deleted,
                    )

            # Verify at least one layer deleted
            if not results["deleted_from"]:
                return error_response(
                    error_code="DELETION_FAILED",
                    message="Document was found but could not be deleted from any storage layer",
                    recovery_strategy="Run health_check to verify storage services are healthy. The document may have been partially deleted.",
                )

            return success_response(
                data=results,
                message=f"Document '{doc.title}' permanently deleted from all storage layers",
            )

        except ValidationError as e:
            return error_response(
                error_code="VALIDATION_ERROR",
                message="Invalid input parameters",
                recovery_strategy="Ensure document_guid and group_guid are valid UUIDs, and confirm is a boolean.",
                details={"errors": e.errors()},
            )

        except Exception as e:
            return error_response(
                error_code="DELETION_FAILED",
                message=f"Unexpected error during deletion: {e!s}",
                recovery_strategy="Run health_check to verify services. Check input parameters and try again.",
            )
