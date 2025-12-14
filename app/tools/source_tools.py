"""MCP Source Tools.

Provides news source registry operations.

Group Access Control:
    - List/get operations use permitted groups from the authenticated token
    - Create operations write to the group associated with the token
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
    get_permitted_groups_from_context,
    get_write_group_from_context,
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
            "List available news sources. "
            "Use to find source_guids before ingesting documents, "
            "or to discover sources by region/type. "
            "Only returns sources from groups you have access to."
        ),
    )
    def list_sources(
        region: Annotated[str | None, Field(
            default=None,
            description="Filter by region code: APAC, JP, CN, HK, SG, AU, KR, TW, US, EU, etc.",
        )] = None,
        source_type: Annotated[str | None, Field(
            default=None,
            description="Filter by type: news_agency, broker, analyst, regulator, other",
        )] = None,
        active_only: Annotated[bool, Field(
            default=True,
            description="Only return active sources (default: True)",
        )] = True,
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
            # Get permitted groups from authentication context
            access_groups = get_permitted_groups_from_context()

            # Query sources with individual filter params
            from app.models.source import SourceType

            source_type_enum = SourceType(source_type) if source_type else None

            sources = source_registry.list_sources(
                access_groups=access_groups,
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
                error_code="LIST_SOURCES_ERROR",
                message=f"Failed to list sources: {e!s}",
                recovery_strategy="Check filter parameters and try again.",
            )

    @mcp.tool(
        name="get_source",
        description=(
            "Get detailed information about a specific news source by its GUID. "
            "Only returns sources from groups you have access to."
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
    ) -> ToolResponse:
        """Get detailed source information.

        Access is automatically limited to groups you have permission to read.
        Anonymous users can only access sources in the public group.

        Args:
            source_guid: The UUID of the source to retrieve (36-char format)

        Returns:
            JSON response with full source details including:
            - source_guid: Unique identifier
            - group_guid: Owning group
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
            # Get permitted groups from authentication context
            access_groups = get_permitted_groups_from_context()

            source = source_registry.get(source_guid, access_groups=access_groups)

            if source is None:
                return error_response(
                    error_code="SOURCE_NOT_FOUND",
                    message=f"Source not found: {source_guid}",
                    recovery_strategy="Verify the source_guid is correct. Use list_sources to see available sources.",
                )

            # Format full source details
            source_data = {
                "source_guid": source.source_guid,
                "group_guid": source.group_guid,
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
                    recovery_strategy="You do not have permission to access this source's group.",
                )
            return error_response(
                error_code="GET_SOURCE_ERROR",
                message=f"Failed to retrieve source: {e!s}",
                recovery_strategy="Check the source_guid format and try again.",
            )

    @mcp.tool(
        name="create_source",
        description=(
            "Create a new news source in the repository. "
            "Use to register a new data provider before ingesting documents from it. "
            "Requires authentication - source is created in your token's group."
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
            description="Type of source: news_agency, broker, analyst, regulator, other",
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
            description="Credibility level: verified, trusted, standard, unverified",
        )] = "unverified",
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
            group_guid: Group name/identifier (string like 'reuters-feed')
        """
        try:
            # Get write group from authentication context
            # Anonymous users cannot write - they get None
            group_guid = get_write_group_from_context()
            
            if group_guid is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required to create sources",
                    recovery_strategy="Provide a valid Bearer token in the Authorization header.",
                )

            from app.models.source import SourceType, TrustLevel

            # Convert string parameters to enums
            try:
                source_type_enum = SourceType(source_type.lower())
            except ValueError:
                return error_response(
                    error_code="INVALID_SOURCE_TYPE",
                    message=f"Invalid source type: {source_type}",
                    recovery_strategy="Valid types: news_agency, broker, analyst, regulator, other",
                )

            try:
                trust_level_enum = TrustLevel(trust_level.lower())
            except ValueError:
                return error_response(
                    error_code="INVALID_TRUST_LEVEL",
                    message=f"Invalid trust level: {trust_level}",
                    recovery_strategy="Valid levels: verified, trusted, standard, unverified",
                )

            # Create the source
            source = source_registry.create(
                name=name,
                group_guid=group_guid,
                source_type=source_type_enum,
                region=region,
                languages=languages or ["en"],
                trust_level=trust_level_enum,
            )

            return success_response(
                data={
                    "source_guid": source.source_guid,
                    "group_guid": source.group_guid,
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
                error_code="CREATE_SOURCE_ERROR",
                message=f"Failed to create source: {e!s}",
                recovery_strategy="Check the input parameters and try again.",
            )
