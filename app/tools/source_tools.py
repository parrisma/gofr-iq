"""MCP Source Tools.

Provides news source registry operations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

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
            "or to discover sources by region/type."
        ),
    )
    def list_sources(
        group_guid: str | None = None,
        region: str | None = None,
        source_type: str | None = None,
        active_only: bool = True,
    ) -> ToolResponse:
        """List registered news sources.

        Args:
            group_guid: Filter by group (optional)
            region: Filter by region: APAC, JP, CN, HK, SG, AU, KR, TW, etc.
            source_type: Filter by type: news_agency, broker, analyst, regulator
            active_only: Only return active sources (default: True)

        Returns:
            sources: List with guid, name, type, region, languages, trust_level
            count: Total matching sources
        """
        try:
            # Get access groups if group_guid provided
            access_groups = [group_guid] if group_guid else None

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
        description="Get detailed information about a specific news source by its GUID.",
    )
    def get_source(
        source_guid: str,
        group_guid: str | None = None,
    ) -> ToolResponse:
        """Get detailed source information.

        Args:
            source_guid: The GUID of the source to retrieve
            group_guid: Optional group GUID for access control validation

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
            # Get access groups if group_guid provided
            access_groups = [group_guid] if group_guid else None

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
            return error_response(
                error_code="GET_SOURCE_ERROR",
                message=f"Failed to retrieve source: {e!s}",
                recovery_strategy="Check the source_guid format and try again.",
            )

    @mcp.tool(
        name="create_source",
        description=(
            "Create a new news source in the repository. "
            "Use to register a new data provider before ingesting documents from it."
        ),
    )
    def create_source(
        name: str,
        group_guid: str,
        source_type: str = "other",
        region: str | None = None,
        languages: list[str] | None = None,
        trust_level: str = "unverified",
    ) -> ToolResponse:
        """Create a new news source.

        Args:
            name: Human-readable source name (e.g., "Reuters", "Bloomberg")
            group_guid: Group this source belongs to
            source_type: Type of source: news_agency, broker, analyst, regulator, other
            region: Geographic region: APAC, JP, CN, HK, SG, AU, KR, TW, US, EU, etc.
            languages: Languages provided (default: ["en"])
            trust_level: Credibility level: high, medium, low, unverified

        Returns:
            source_guid: The newly created source identifier
            name: Source name
            type: Source type
            region: Geographic region
            languages: Supported languages
            trust_level: Trust level assigned
        """
        try:
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
