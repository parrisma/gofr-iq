"""MCP Source Tools.

Provides news source registry operations.

Access Control:
    - Admin-only operations: create_source, update_source, delete_source
    - List/get operations: accessible to all authenticated users
    - Sources are global (not tied to groups) - any document can reference any source
    - Anonymous users can only access the public group
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

from app.services.group_service import (
    AdminAccessDeniedError,
    require_admin,
    resolve_write_group,
)
from app.services.source_registry import SourceNotFoundError, SourceRegistry

if TYPE_CHECKING:
    pass

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def register_source_tools(mcp: FastMCP, source_registry: SourceRegistry) -> None:
    """Register source tools with the MCP server."""

    @mcp.tool(
        name="list_sources",
        description=(
            "List available news sources (Reuters, Bloomberg, etc). "
            "USE BEFORE: ingest_document - you need a source_guid. "
            "FILTER BY: region (APAC, US, EU), type (news_agency, broker, analyst). "
            "RETURNS: source_guid, name, type, region, trust_level. "
            "WORKFLOW: list_sources -> get_source -> ingest_document OR create_source (if new provider). "
            "OUTPUT TO: ingest_document(source_guid=...) | get_source(source_guid=...). "
            "TIP: Call this first if you need to ingest documents."
        ),
    )
    def list_sources(
        region: Annotated[str | None, Field(
            default=None,
            description="Filter by region code: APAC, JP, CN, HK, SG, AU, KR, TW, US, EU, etc.",
            examples=["APAC", "US"],
        )] = None,
        source_type: Annotated[str | None, Field(
            default=None,
            description="Filter: news_agency|internal|research|government|corporate|social|other",
            examples=["news_agency", "research"],
        )] = None,
        active_only: Annotated[bool, Field(
            default=True,
            description="Only return active sources (default: True)",
        )] = True,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """List registered news sources.

        Results are automatically limited to groups you have permission to access.
        Anonymous users can only see sources in the public group.

        Args:
            region: Filter by region: APAC, JP, CN, HK, SG, AU, KR, TW, etc.
            source_type: Filter by type: news_agency, broker, analyst, regulator
            active_only: Only return active sources (default: True)

        Returns:
            sources: List with guid, name, type, region, languages, trust_level
            count: Total matching sources
        """
        try:
            # Sources are global - no access_groups parameter needed
            # All authenticated users can list sources
            
            # Query sources with individual filter params
            from app.models.source import SourceType

            source_type_enum = SourceType(source_type) if source_type else None

            sources = source_registry.list_sources(
                region=region,
                source_type=source_type_enum,
                include_inactive=not active_only,
            )

            # Format response
            source_list = [
                {
                    "source_guid": s.source_guid,
                    "name": s.name,
                    "type": s.type.value if s.type else None,
                    "region": s.region,
                    "languages": s.languages,
                    "trust_level": s.trust_level.value if s.trust_level else None,
                    "active": s.active,
                }
                for s in sources
            ]

            return success_response(
                data={"sources": source_list, "count": len(source_list)}
            )

        except Exception as e:
            return error_response(
                error_code="SOURCE_LIST_FAILED",
                message=f"Failed to list sources: {e!s}",
                recovery_strategy="Run health_check to verify services. Check filter parameters.",
            )

    @mcp.tool(
        name="get_source",
        description=(
            "Get detailed information about a specific news source. "
            "USE FOR: Checking source credibility, supported languages, metadata. "
            "RETURNS: Full source details including trust_level, boost_factor, active status. "
            "WORKFLOW: list_sources -> get_source -> verify before ingesting. "
            "INPUT FROM: list_sources (source_guid output). "
            "OUTPUT TO: Verify metadata before ingest_document | update_source | delete_source. "
            "PREREQUISITE: You need a source_guid (from list_sources or document metadata)."
        ),
    )
    def get_source(
        source_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the source to retrieve (36-char UUID format)",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Get detailed source information.

        Access is automatically limited to groups you have permission to read.
        Anonymous users can only access sources in the public group.

        Args:
            source_guid: The UUID of the source to retrieve (36-char format)

        Returns:
            JSON response with full source details including:
            - source_guid: Unique identifier
            - name: Display name
            - type: Source type (news_agency, broker, analyst, etc.)
            - region: Geographic region
            - languages: Supported languages
            - trust_level: Trust level for scoring
            - boost_factor: Relevance boost factor
            - active: Whether the source is active
            - created_at: Creation timestamp
            - updated_at: Last update timestamp
            - metadata: Additional source metadata

        Errors:
            - SOURCE_NOT_FOUND: The source_guid doesn't exist or isn't accessible
        """
        try:
            source = source_registry.get(source_guid)

            if source is None:
                return error_response(
                    error_code="SOURCE_NOT_FOUND",
                    message=f"Source not found: {source_guid}",
                    recovery_strategy="Call list_sources to find valid source GUIDs.",
                    details={"source_guid": source_guid},
                )

            # Format full source details
            source_data = {
                "source_guid": source.source_guid,
                "name": source.name,
                "type": source.type.value if source.type else None,
                "region": source.region,
                "languages": source.languages,
                "trust_level": source.trust_level.value if source.trust_level else None,
                "boost_factor": source.boost_factor,
                "active": source.active,
                "created_at": source.created_at.isoformat() if source.created_at else None,
                "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                "metadata": source.metadata,
            }

            return success_response(data=source_data)

        except SourceNotFoundError:
            return error_response(
                error_code="SOURCE_NOT_FOUND",
                message=f"Source not found: {source_guid}",
                recovery_strategy="Verify the source_guid is correct. Use list_sources to see available sources.",
            )

        except Exception as e:
            error_msg = str(e)
            # Check for access denied errors
            if "access denied" in error_msg.lower():
                return error_response(
                    error_code="ACCESS_DENIED",
                    message=f"Access denied to source: {source_guid}",
                    recovery_strategy="Source belongs to a group you can't access. Call list_sources to see accessible sources.",
                    details={"source_guid": source_guid},
                )
            return error_response(
                error_code="SOURCE_RETRIEVAL_FAILED",
                message=f"Failed to retrieve source: {e!s}",
                recovery_strategy="Run health_check to verify services. Check source_guid format (UUID).",
                details={"source_guid": source_guid},
            )

    @mcp.tool(
        name="create_source",
        description=(
            "[ADMIN ONLY] Register a new news source (e.g., Reuters, internal feed). "
            "USE BEFORE: ingest_document from a new provider. "
            "REQUIRES: Admin group membership. "
            "TYPES: news_agency, broker, analyst, regulator, other. "
            "WORKFLOW: list_sources (not found?) -> create_source -> ingest_document. "
            "OUTPUT TO: ingest_document(source_guid=...) | get_source(source_guid=...). "
            "RETURNS: source_guid to use when ingesting documents from this source."
        ),
    )
    def create_source(
        name: Annotated[str, Field(
            min_length=1,
            max_length=255,
            description="Human-readable source name (e.g., 'Reuters', 'Bloomberg')",
        )],
        source_type: Annotated[str, Field(
            default="other",
            description="Type: news_agency|internal|research|government|corporate|social|other",
            examples=["news_agency", "research"],
        )] = "other",
        region: Annotated[str | None, Field(
            default=None,
            description="Geographic region: APAC, JP, CN, HK, SG, AU, KR, TW, US, EU, etc.",
        )] = None,
        languages: Annotated[list[str] | None, Field(
            default=None,
            description="Languages provided as ISO 639-1 codes (default: ['en'])",
        )] = None,
        trust_level: Annotated[str, Field(
            default="unverified",
            description="Level: high (1.2x)|medium (1.0x)|low (0.8x)|unverified (0.6x boost)",
            examples=["high", "medium"],
        )] = "unverified",
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Create a new news source.

        The source is automatically created in the group associated with
        your authentication token. The group is a string identifier like
        'reuters-feed' or 'sales-team-nyc', not a UUID.
        Anonymous users cannot create sources.

        Args:
            name: Human-readable source name (e.g., 'Reuters', 'Bloomberg')
            source_type: Type of source: news_agency, broker, analyst, regulator, other
            region: Geographic region: APAC, JP, CN, HK, SG, AU, KR, TW, US, EU, etc.
            languages: Languages provided as ISO 639-1 codes (default: ['en'])
            trust_level: Credibility level: verified, trusted, standard, unverified

        Returns:
            source_guid: The newly created source identifier (UUID)
            name: Source name
            type: Source type
            region: Geographic region
            languages: Supported languages
            trust_level: Trust level assigned
        """
        try:
            # Admin access required
            try:
                require_admin(auth_tokens=auth_tokens)
            except AdminAccessDeniedError as e:
                return error_response(
                    error_code="PERMISSION_DENIED",
                    message=str(e),
                    recovery_strategy="Use a token with admin group membership to create sources.",
                )

            from app.models.source import SourceType, TrustLevel

            # Convert string parameters to enums
            try:
                source_type_enum = SourceType(source_type.lower())
            except ValueError:
                return error_response(
                    error_code="INVALID_SOURCE_TYPE",
                    message=f"Invalid source type: {source_type}",
                    recovery_strategy="Valid types: news_agency|internal|research|government|corporate|social|other",
                    details={"provided": source_type},
                )

            try:
                trust_level_enum = TrustLevel(trust_level.lower())
            except ValueError:
                return error_response(
                    error_code="INVALID_TRUST_LEVEL",
                    message=f"Invalid trust level: {trust_level}",
                    recovery_strategy="Valid levels: high (1.2x)|medium (1.0x)|low (0.8x)|unverified (0.6x boost)",
                    details={"provided": trust_level},
                )

            # Create the source (standalone entity)
            source = source_registry.create(
                name=name,
                source_type=source_type_enum,
                region=region,
                languages=languages or ["en"],
                trust_level=trust_level_enum,
            )

            return success_response(
                data={
                    "source_guid": source.source_guid,
                    "name": source.name,
                    "type": source.type.value if source.type else None,
                    "region": source.region,
                    "languages": source.languages,
                    "trust_level": source.trust_level.value if source.trust_level else None,
                    "active": source.active,
                    "created_at": source.created_at.isoformat() if source.created_at else None,
                },
                message=f"Source '{name}' created successfully",
            )

        except Exception as e:
            return error_response(
                error_code="SOURCE_CREATE_FAILED",
                message=f"Failed to create source: {e!s}",
                recovery_strategy="Run health_check to verify services. Check name is unique and parameters are valid.",
                details={"attempted_name": name},
            )

    @mcp.tool(
        name="update_source",
        description=(
            "[ADMIN ONLY] Update an existing news source's properties (name, type, region, languages, trust_level). "
            "USE WHEN: Modifying source metadata, adjusting trust levels, or updating coverage details. "
            "REQUIRES: Admin group membership. "
            "PARTIAL UPDATE: Only provided fields are changed. "
            "RETURNS: Updated source details."
        ),
    )
    def update_source(
        source_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the source to update",
            examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"],
        )],
        name: Annotated[str | None, Field(
            default=None,
            min_length=1,
            max_length=255,
            description="New human-readable source name",
        )] = None,
        source_type: Annotated[str | None, Field(
            default=None,
            description="Type: news_agency|internal|research|government|corporate|social|other",
            examples=["news_agency", "research"],
        )] = None,
        region: Annotated[str | None, Field(
            default=None,
            description="New geographic region: APAC, JP, CN, HK, SG, AU, KR, TW, US, EU, etc.",
        )] = None,
        languages: Annotated[list[str] | None, Field(
            default=None,
            description="New languages as ISO 639-1 codes (e.g., ['en', 'zh'])",
        )] = None,
        trust_level: Annotated[str | None, Field(
            default=None,
            description="Level: high (1.2x)|medium (1.0x)|low (0.8x)|unverified (0.6x boost)",
            examples=["high", "medium"],
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Update an existing news source.

        Only provided fields are updated. Omit fields to keep their current values.
        Requires write access to the source's group.

        Args:
            source_guid: UUID of the source to update
            name: New human-readable source name (optional)
            source_type: New source type (optional)
            region: New geographic region (optional)
            languages: New list of language codes (optional)
            trust_level: New trust level - affects scoring boost (optional)
            auth_tokens: JWT tokens for authentication

        Returns:
            Updated source details including all fields and updated_at timestamp.

        Errors:
            - SOURCE_NOT_FOUND: The source_guid doesn't exist or isn't accessible
            - AUTH_REQUIRED: No valid authentication token provided
            - ACCESS_DENIED: User doesn't have write access to source's group
            - INVALID_SOURCE_TYPE: Invalid source_type value
            - INVALID_TRUST_LEVEL: Invalid trust_level value
        """
        try:
            # Admin access required
            try:
                require_admin(auth_tokens=auth_tokens)
            except AdminAccessDeniedError as e:
                return error_response(
                    error_code="PERMISSION_DENIED",
                    message=str(e),
                    recovery_strategy="Use a token with admin group membership to update sources.",
                )

            # Validate write access (anonymous cannot update)
            write_group_name = resolve_write_group(auth_tokens=auth_tokens)
            if write_group_name is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required to update sources",
                    recovery_strategy="Pass auth_tokens parameter or include Authorization header with Bearer token.",
                )

            from app.models.source import SourceType, TrustLevel

            # Convert enums if provided
            source_type_enum = None
            if source_type is not None:
                try:
                    source_type_enum = SourceType(source_type.lower())
                except ValueError:
                    return error_response(
                        error_code="INVALID_SOURCE_TYPE",
                        message=f"Invalid source type: {source_type}",
                        recovery_strategy="Valid types: news_agency|internal|research|government|corporate|social|other",
                        details={"provided": source_type},
                    )

            trust_level_enum = None
            if trust_level is not None:
                try:
                    trust_level_enum = TrustLevel(trust_level.lower())
                except ValueError:
                    return error_response(
                        error_code="INVALID_TRUST_LEVEL",
                        message=f"Invalid trust level: {trust_level}",
                        recovery_strategy="Valid levels: high (1.2x)|medium (1.0x)|low (0.8x)|unverified (0.6x boost)",
                        details={"provided": trust_level},
                    )

            # Update the source
            source = source_registry.update(
                source_guid=source_guid,
                name=name,
                source_type=source_type_enum,
                region=region,
                languages=languages,
                trust_level=trust_level_enum,
            )

            # Build response
            return success_response(
                data={
                    "source_guid": source.source_guid,
                    "name": source.name,
                    "type": source.type.value if source.type else None,
                    "region": source.region,
                    "languages": source.languages,
                    "trust_level": source.trust_level.value if source.trust_level else None,
                    "boost_factor": source.boost_factor,
                    "active": source.active,
                    "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                },
                message=f"Source '{source.name}' updated successfully",
            )

        except SourceNotFoundError:
            return error_response(
                error_code="SOURCE_NOT_FOUND",
                message=f"Source not found: {source_guid}",
                recovery_strategy="Call list_sources to find valid source GUIDs, or create_source to create one.",
                details={"source_guid": source_guid},
            )

        except Exception as e:
            error_msg = str(e)
            if "access denied" in error_msg.lower():
                return error_response(
                    error_code="ACCESS_DENIED",
                    message=f"Access denied to update source: {source_guid}",
                    recovery_strategy="You need write access to this source's group.",
                    details={"source_guid": source_guid},
                )
            return error_response(
                error_code="SOURCE_UPDATE_FAILED",
                message=f"Failed to update source: {e!s}",
                recovery_strategy="Run health_check to verify services. Check source_guid and parameters.",
                details={"source_guid": source_guid},
            )

    @mcp.tool(
        name="delete_source",
        description=(
            "[ADMIN ONLY] Delete (deactivate) a news source. "
            "USE WHEN: Retiring a source, removing outdated feeds, or cleanup. "
            "REQUIRES: Admin group membership. "
            "SOFT DELETE: Source is marked inactive but not removed from storage. "
            "RETURNS: Confirmation of deletion with source details."
        ),
    )
    def delete_source(
        source_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the source to delete",
            examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Delete (soft-delete) a news source.

        The source is marked as inactive rather than being permanently deleted.
        Documents from this source remain in the system but the source won't
        appear in active source lists.

        Args:
            source_guid: UUID of the source to delete
            auth_tokens: JWT tokens for authentication

        Returns:
            Confirmation with deleted source details.

        Errors:
            - SOURCE_NOT_FOUND: The source_guid doesn't exist or isn't accessible
            - AUTH_REQUIRED: No valid authentication token provided
            - ACCESS_DENIED: User doesn't have write access to source's group
        """
        try:
            # Admin access required
            try:
                require_admin(auth_tokens=auth_tokens)
            except AdminAccessDeniedError as e:
                return error_response(
                    error_code="PERMISSION_DENIED",
                    message=str(e),
                    recovery_strategy="Use a token with admin group membership to delete sources.",
                )

            # Validate write access (anonymous cannot delete)
            write_group_name = resolve_write_group(auth_tokens=auth_tokens)
            if write_group_name is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required to delete sources",
                    recovery_strategy="Pass auth_tokens parameter or include Authorization header with Bearer token.",
                )

            # Soft-delete the source
            source = source_registry.soft_delete(
                source_guid=source_guid,
            )

            return success_response(
                data={
                    "source_guid": source.source_guid,
                    "name": source.name,
                    "type": source.type.value if source.type else None,
                    "active": source.active,
                    "deleted_at": source.updated_at.isoformat() if source.updated_at else None,
                },
                message=f"Source '{source.name}' has been deleted (marked inactive)",
            )

        except SourceNotFoundError:
            return error_response(
                error_code="SOURCE_NOT_FOUND",
                message=f"Source not found: {source_guid}",
                recovery_strategy="Call list_sources to find valid source GUIDs.",
                details={"source_guid": source_guid},
            )

        except Exception as e:
            error_msg = str(e)
            if "access denied" in error_msg.lower():
                return error_response(
                    error_code="ACCESS_DENIED",
                    message=f"Access denied to delete source: {source_guid}",
                    recovery_strategy="You need write access to this source's group.",
                    details={"source_guid": source_guid},
                )
            return error_response(
                error_code="SOURCE_DELETE_FAILED",
                message=f"Failed to delete source: {e!s}",
                recovery_strategy="Run health_check to verify services. Check source_guid.",
                details={"source_guid": source_guid},
            )
