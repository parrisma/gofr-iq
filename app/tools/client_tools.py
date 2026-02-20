"""MCP Client Tools.

Provides client profile management and personalized news feeds.

Group Access Control:
    - Client creation requires authentication
    - Feeds are filtered to groups the user has access to
    - Portfolio/watchlist operations require client access
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, ValidationError

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

from app.models.restrictions import ClientRestrictions
from app.services.client_service import ClientService
from app.services.graph_index import GraphIndex, NodeLabel, RelationType
from app.services.group_service import (
    get_group_uuid_by_name,
    get_group_uuids_by_names,
    resolve_permitted_groups,
    resolve_write_group,
)

if TYPE_CHECKING:
    from app.services.llm_service import LLMService
    from app.services.query_service import QueryService

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def _require_admin_group(auth_tokens: list[str] | None) -> tuple[bool, list[str]]:
    group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
    return "admin" in group_names, group_names


def _resolve_instrument_guid(
    graph_index: GraphIndex,
    ticker: str,
    instrument_type: str = "STOCK",
) -> str:
    """Find an existing Instrument by ticker, or create one.

    The universe builder creates instruments with ``guid = 'inst-{TICKER}'``
    while a bare MCP creation would use ``'{TICKER}:UNKNOWN'``.  We must
    resolve the *actual* GUID stored in the graph to avoid dangling
    relationship errors.

    Returns:
        The ``guid`` of the matched or newly-created Instrument node.
    """
    upper = ticker.upper()
    # 1. Look up by ticker property (covers instruments from any source)
    with graph_index._get_session() as session:
        result = session.run(
            "MATCH (i:Instrument {ticker: $ticker}) RETURN i.guid AS guid",
            ticker=upper,
        )
        record = result.single()
        if record:
            return record["guid"]

    # 2. Not found – create a minimal placeholder so the relationship works
    node = graph_index.create_instrument(
        ticker=upper,
        name=upper,
        instrument_type=instrument_type,
        exchange="UNKNOWN",
    )
    return node.guid


def register_client_tools(
    mcp: FastMCP,
    graph_index: GraphIndex,
    query_service: "QueryService | None" = None,
    llm_service: "LLMService | None" = None,
) -> None:
    """Register client tools with the MCP server."""
    client_service = ClientService(graph_index)

    @mcp.tool(
        name="create_client",
        description=(
            "Create an investment client profile for personalized news feeds. "
            "WORKFLOW: create_client -> get_client_profile -> add_to_portfolio/add_to_watchlist -> get_client_feed. "
            "USE FOR: Setting up hedge funds, asset managers, family offices, etc. "
            "REQUIRES AUTH: Must have a valid token. "
            "CREATES: Client + empty portfolio + empty watchlist. "
            "OUTPUT TO: get_client_profile (retrieve) | add_to_portfolio (add holdings) | add_to_watchlist (watch tickers). "
            "NEXT STEPS: Use add_to_portfolio/add_to_watchlist to populate holdings.\""
        ),
    )
    def create_client(
        name: Annotated[str, Field(
            min_length=1,
            max_length=255,
            description="Client name (e.g., 'Citadel', 'BlackRock')",
            examples=["Citadel", "BlackRock APAC"],
        )],
        client_type: Annotated[str, Field(
            default="HEDGE_FUND",
            description="Type: HEDGE_FUND|LONG_ONLY|QUANT|PENSION|FAMILY_OFFICE",
            examples=["HEDGE_FUND", "PENSION"],
        )] = "HEDGE_FUND",
        alert_frequency: Annotated[str, Field(
            default="realtime",
            description="Alerts: realtime|hourly|daily|weekly",
            examples=["realtime", "daily"],
        )] = "realtime",
        impact_threshold: Annotated[float, Field(
            default=50.0,
            ge=0.0,
            le=100.0,
            description="Minimum impact score 0-100 for alerts (default: 50)",
        )] = 50.0,
        mandate_type: Annotated[str | None, Field(
            default=None,
            description="Investment mandate style (e.g., 'equity_long_short', 'global_macro')",
            examples=["equity_long_short", "global_macro"],
        )] = None,
        mandate_text: Annotated[str | None, Field(
            default=None,
            max_length=5000,
            description="Free-text fund mandate description (0-5000 chars, optional)",
            examples=["Our fund focuses on US technology stocks with strong ESG ratings."],
        )] = None,
        benchmark: Annotated[str | None, Field(
            default=None,
            description="Benchmark ticker symbol (e.g., 'SPY', 'QQQ')",
            examples=["SPY", "QQQ", "IWM"],
        )] = None,
        horizon: Annotated[str | None, Field(
            default=None,
            description="Horizon: short (<1mo)|medium (1-6mo)|long (>6mo)",
            examples=["short", "long"],
        )] = None,
        esg_constrained: Annotated[bool, Field(
            default=False,
            description="Apply ESG filters to news feed",
        )] = False,
        restrictions: Annotated[dict[str, Any] | None, Field(
            default=None,
            description=(
                "Structured ESG & compliance restrictions object. "
                "Categories: ethical_sector (excluded_industries, faith_based), "
                "impact_sustainability (impact_mandate, impact_themes, stewardship_obligations), "
                "legal_regulatory, operational_risk, tax_accounting. "
                "If ethical_sector.excluded_industries is non-empty, esg_constrained is auto-set to True."
            ),
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Create a new client profile.

        The client is automatically created in the group associated with
        your authentication token. The group is a string identifier like
        'reuters-feed' or 'sales-team-nyc', not a UUID.
        Anonymous users cannot create clients.

        Args:
            name: Client name (e.g., 'Citadel', 'BlackRock')
            client_type: HEDGE_FUND, LONG_ONLY, QUANT, PENSION, or FAMILY_OFFICE
            alert_frequency: realtime, hourly, daily, or weekly
            impact_threshold: Min impact score 0-100 for alerts (default: 50)
            mandate_type: Investment style (e.g., 'equity_long_short')
            mandate_text: Free-text mandate description (0-5000 chars)
            benchmark: Benchmark ticker (e.g., 'SPY')
            horizon: short, medium, or long
            esg_constrained: Apply ESG filters
            restrictions: Structured ESG & compliance restrictions dict

        Returns:
            client_guid, portfolio_guid, watchlist_guid, profile settings,
            group_guid: Group name/identifier (string like 'reuters-feed')
        """
        import uuid

        try:
            # Get write group from explicit tokens or context header
            write_group_name = resolve_write_group(auth_tokens=auth_tokens)
            
            if write_group_name is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required to create clients",
                    recovery_strategy="Pass auth_tokens parameter or include Authorization header with Bearer token.",
                )
            
            # Convert group name to UUID for storage layer
            group_guid = get_group_uuid_by_name(write_group_name)
            if group_guid is None:
                return error_response(
                    error_code="GROUP_NOT_FOUND",
                    message=f"Group not found: {write_group_name}",
                    recovery_strategy="Ensure the group exists in the auth system.",
                    details={"group_name": write_group_name},
                )

            client_guid = str(uuid.uuid4())
            
            # Validate mandate_text length if provided
            if mandate_text is not None and len(mandate_text) > 5000:
                return error_response(
                    error_code="MANDATE_TEXT_TOO_LONG",
                    message=f"Mandate text exceeds 5000 character limit: {len(mandate_text)} chars",
                    recovery_strategy="Shorten the text to 5000 characters or less.",
                    details={"length": len(mandate_text), "max_length": 5000},
                )
            
            # Ensure Group node exists in Neo4j (may not exist if this is first client in group)
            # This is idempotent - MERGE will not duplicate if it already exists
            graph_index.create_group(
                guid=group_guid,
                name=write_group_name,
            )
            
            # Create client type if it doesn't exist
            # Convert frequency string to int (realtime=100, hourly=24, daily=1, weekly=0)
            freq_map = {"realtime": 100, "hourly": 24, "daily": 1, "weekly": 0}
            alert_freq_int = freq_map.get(alert_frequency, 10)
            
            try:
                graph_index.create_client_type(
                    code=client_type,
                    name=client_type.replace("_", " ").title(),
                    default_alert_frequency=alert_freq_int,
                    default_impact_threshold=int(impact_threshold),
                )
            except Exception:
                pass  # nosec B110 - Type may already exist
            
            # Create the client with settings in properties
            graph_index.create_client(
                guid=client_guid,
                name=name,
                client_type_code=client_type,
                group_guid=group_guid,
                properties={
                    "alert_frequency": alert_frequency,
                    "impact_threshold": impact_threshold,
                    "status": "active",
                },
            )
            
            # Create profile
            profile_guid = str(uuid.uuid4())
            profile_properties: dict[str, Any] = {}
            if mandate_text:
                profile_properties["mandate_text"] = mandate_text.strip()
            
            # Validate and store restrictions
            validated_restrictions: ClientRestrictions | None = None
            restrictions_json: str | None = None
            if restrictions:
                try:
                    validated_restrictions = ClientRestrictions(**restrictions)
                    restrictions_json = validated_restrictions.model_dump_json()
                    profile_properties["restrictions"] = restrictions_json
                    # Auto-enable esg_constrained if exclusions are defined
                    if validated_restrictions.has_exclusions():
                        esg_constrained = True
                except ValidationError as ve:
                    return error_response(
                        error_code="INVALID_RESTRICTIONS",
                        message="Invalid restrictions schema",
                        recovery_strategy="Check restrictions structure against documented schema.",
                        details={"validation_errors": ve.errors()},
                    )
            
            graph_index.create_client_profile(
                guid=profile_guid,
                client_guid=client_guid,
                mandate_type=mandate_type,
                benchmark_guid=benchmark,  # Will be None if not an actual GUID
                horizon=horizon,
                esg_constrained=esg_constrained,
                properties=profile_properties,
            )
            
            # Auto-enrich mandate_themes from mandate_text (LLM at create-time)
            # Matches update_client_profile behavior for consistency
            enriched_themes: list[str] | None = None
            if mandate_text and mandate_text.strip():
                from app.services.mandate_enrichment import extract_themes_from_mandate
                from app.services.llm_service import create_llm_service
                
                try:
                    with create_llm_service() as llm_service:
                        enrichment_result = extract_themes_from_mandate(
                            mandate_text.strip(), llm_service
                        )
                        if enrichment_result.success and enrichment_result.themes:
                            enriched_themes = enrichment_result.themes
                            # Update the profile node with enriched themes
                            with graph_index._get_session() as session:
                                session.run(
                                    """
                                    MATCH (cp:ClientProfile {guid: $profile_guid})
                                    SET cp.mandate_themes = $themes
                                    """,
                                    profile_guid=profile_guid,
                                    themes=enriched_themes,
                                )
                except Exception:  # nosec B110 - enrichment failure is non-fatal; themes can be set manually
                    pass
            
            # Create empty portfolio and watchlist
            portfolio_guid = str(uuid.uuid4())
            watchlist_guid = str(uuid.uuid4())
            
            graph_index.create_portfolio(
                guid=portfolio_guid,
                client_guid=client_guid,
                properties={"name": f"{name} Portfolio"},
            )

            try:
                graph_index.create_relationship(
                    RelationType.IN_GROUP,
                    NodeLabel.PORTFOLIO,
                    portfolio_guid,
                    NodeLabel.GROUP,
                    group_guid,
                )
            except RuntimeError:
                pass
            
            graph_index.create_watchlist(
                guid=watchlist_guid,
                client_guid=client_guid,
                name=f"{name} Watchlist",
            )

            try:
                graph_index.create_relationship(
                    RelationType.IN_GROUP,
                    NodeLabel.WATCHLIST,
                    watchlist_guid,
                    NodeLabel.GROUP,
                    group_guid,
                )
            except RuntimeError:
                pass
            
            return success_response(
                data={
                    "client_guid": client_guid,
                    "name": name,
                    "client_type": client_type,
                    "group_guid": group_guid,
                    "portfolio_guid": portfolio_guid,
                    "watchlist_guid": watchlist_guid,
                    "profile": {
                        "guid": profile_guid,
                        "mandate_type": mandate_type,
                        "mandate_text": mandate_text,
                        "mandate_themes": enriched_themes,
                        "benchmark": benchmark,
                        "horizon": horizon,
                        "esg_constrained": esg_constrained,
                        "restrictions": validated_restrictions.model_dump() if validated_restrictions else None,
                    },
                    "settings": {
                        "alert_frequency": alert_frequency,
                        "impact_threshold": impact_threshold,
                    },
                },
                message=f"Client '{name}' created successfully",
            )

        except Exception as e:
            return error_response(
                error_code="CLIENT_CREATE_FAILED",
                message=f"Failed to create client: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j connectivity. Ensure name is unique.",
                details={"attempted_name": name, "client_type": client_type},
            )

    @mcp.tool(
        name="get_client_feed",
        description=(
            "Get personalized news feed for a client based on their holdings. "
            "USE FOR: 'What news matters to Citadel?' or 'Show me my client's feed'. "
            "RANKED BY: Impact score + relevance to portfolio/watchlist positions. "
            "PREREQUISITE: Client must exist (use create_client first). "
            "RETURNS: Articles with impact_score, affected tickers, relevance."
        ),
    )
    def get_client_feed(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to get feed for",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        limit: Annotated[int, Field(
            default=20,
            ge=1,
            le=100,
            description="Maximum articles to return (default: 20, max: 100)",
        )] = 20,
        min_impact_score: Annotated[float | None, Field(
            default=None,
            ge=0.0,
            le=100.0,
            description="Minimum importance score 0-100 to filter articles",
        )] = None,
        impact_tiers: Annotated[list[str] | None, Field(
            default=None,
            description="Filter by impact tiers: PLATINUM, GOLD, SILVER, BRONZE, STANDARD",
            examples=[["PLATINUM", "GOLD"]],
        )] = None,
        include_portfolio: Annotated[bool, Field(
            default=True,
            description="Include news for portfolio holdings (default: True)",
        )] = True,
        include_watchlist: Annotated[bool, Field(
            default=True,
            description="Include news for watched stocks (default: True)",
        )] = True,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Get personalized news feed for a client.

        Feed is automatically limited to groups you have permission to access.
        Groups are string identifiers like 'reuters-feed' or 'public', not UUIDs.
        Anonymous users only see news from the public group.

        Args:
            client_guid: UUID of the client to get feed for (36-char format)
            limit: Max articles (default: 20)
            min_impact_score: Min importance 0-100
            impact_tiers: PLATINUM, GOLD, SILVER, BRONZE, STANDARD
            include_portfolio: Include news for holdings (default: True)
            include_watchlist: Include news for watched stocks (default: True)

        Returns:
            articles: Ranked list with title, impact, relevance, affected tickers
            total_count: Number of articles
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            # Convert group names to UUIDs for storage layer
            group_guids = get_group_uuids_by_names(group_names)

            # Validate client exists
            client_node = graph_index.get_node(NodeLabel.CLIENT, client_guid)
            if not client_node:
                return error_response(
                    error_code="CLIENT_NOT_FOUND",
                    message=f"Client not found: {client_guid}",
                    recovery_strategy="Call list_clients to find valid client GUIDs, or create_client to create one.",
                    details={"client_guid": client_guid},
                )

            if client_node.properties.get("status") == "defunct":
                return error_response(
                    error_code="CLIENT_DEFUNCT",
                    message="Client is defunct and cannot receive feeds",
                    recovery_strategy="Restore the client or select an active client.",
                    details={
                        "client_guid": client_guid,
                        "defunct_at": client_node.properties.get("defunct_at"),
                        "defunct_reason": client_node.properties.get("defunct_reason"),
                    },
                )
            
            # Get feed from graph
            feed_results = graph_index.get_client_feed(
                client_guid=client_guid,
                permitted_groups=group_guids,
                limit=limit,
                min_impact_score=min_impact_score,
                impact_tiers=impact_tiers,
                include_portfolio=include_portfolio,
                include_watchlist=include_watchlist,
            )
            
            # Format response
            articles = []
            for result in feed_results:
                articles.append({
                    "document_guid": result.get("document_guid"),
                    "title": result.get("title"),
                    "impact_score": result.get("impact_score"),
                    "impact_tier": result.get("impact_tier"),
                    "relevance_score": result.get("relevance_score", result.get("current_relevance")),
                    "affected_instruments": result.get("affected_instruments", []),
                    "created_at": result.get("created_at"),
                })
            
            filters_applied = {
                "min_impact_score": min_impact_score,
                "impact_tiers": impact_tiers,
                "include_portfolio": include_portfolio,
                "include_watchlist": include_watchlist,
            }
            
            return success_response(
                data={
                    "articles": articles,
                    "total_count": len(articles),
                    "filters_applied": filters_applied,
                },
                message=f"Retrieved {len(articles)} articles for client",
            )

        except Exception as e:
            return error_response(
                error_code="FEED_RETRIEVAL_FAILED",
                message=f"Failed to retrieve client feed: {e!s}",
                recovery_strategy="Verify client with get_client_profile. Run health_check if Neo4j may be down.",
                details={"client_guid": client_guid, "limit": limit},
            )

    @mcp.tool(
        name="get_client_avatar_feed",
        description=(
            "Get two-channel avatar news feed for a client. "
            "MAINTENANCE channel: news about existing holdings/watchlist. "
            "OPPORTUNITY channel: mandate-themed news for new ideas (excludes positions). "
            "USE FOR: 'What should I know and what opportunities exist?' "
            "PREREQUISITE: Client with portfolio + mandate_themes. "
            "RETURNS: maintenance items, opportunity items, combined ranked list."
        ),
    )
    def get_client_avatar_feed(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to get avatar feed for",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        limit: Annotated[int, Field(
            default=20,
            ge=1,
            le=100,
            description="Maximum total items across both channels (default: 20, max: 100)",
        )] = 20,
        time_window_hours: Annotated[int, Field(
            default=72,
            ge=1,
            le=720,
            description="How many hours back to look for news (default: 72, max: 720)",
        )] = 72,
        min_impact_score: Annotated[float | None, Field(
            default=None,
            ge=0.0,
            le=100.0,
            description="Minimum impact score filter (0-100). Defaults to client's impact_threshold.",
        )] = None,
        impact_tiers: Annotated[list[str] | None, Field(
            default=None,
            description="Filter by impact tiers: PLATINUM, GOLD, SILVER, BRONZE, STANDARD",
            examples=[["PLATINUM", "GOLD", "SILVER"]],
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication",
        )] = None,
    ) -> ToolResponse:
        """Get two-channel avatar news feed.

        Channel 1 (MAINTENANCE): News affecting your holdings and watchlist.
        Channel 2 (OPPORTUNITY): Mandate-themed news NOT affecting existing positions.

        Both channels are ranked by relevance. Deterministic (no LLM at query time).
        """
        if not query_service:
            return error_response(
                error_code="SERVICE_UNAVAILABLE",
                message="Avatar feed service is not configured",
                recovery_strategy="Ensure QueryService is initialized with graph_index.",
            )

        try:
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            group_guids = get_group_uuids_by_names(group_names)

            # Validate client exists
            client_node = graph_index.get_node(NodeLabel.CLIENT, client_guid)
            if not client_node:
                return error_response(
                    error_code="CLIENT_NOT_FOUND",
                    message=f"Client not found: {client_guid}",
                    recovery_strategy="Call list_clients to find valid client GUIDs.",
                    details={"client_guid": client_guid},
                )

            if client_node.properties.get("status") == "defunct":
                return error_response(
                    error_code="CLIENT_DEFUNCT",
                    message="Client is defunct and cannot receive feeds",
                    recovery_strategy="Restore the client or select an active client.",
                    details={"client_guid": client_guid},
                )

            feed = query_service.get_client_avatar_feed(
                client_guid=client_guid,
                group_guids=group_guids,
                limit=limit,
                time_window_hours=time_window_hours,
                min_impact_score=min_impact_score,
                impact_tiers=impact_tiers,
            )

            def _serialize_item(item):
                return {
                    "document_guid": item.document_guid,
                    "title": item.title,
                    "created_at": item.created_at,
                    "impact_score": item.impact_score,
                    "impact_tier": item.impact_tier,
                    "affected_instruments": item.affected_instruments,
                    "themes": item.themes,
                    "relevance_score": round(item.relevance_score, 4),
                    "channel": item.channel,
                    "reason": item.reason,
                }

            return success_response(
                data={
                    "client_guid": feed.client_guid,
                    "maintenance": [_serialize_item(i) for i in feed.maintenance],
                    "opportunity": [_serialize_item(i) for i in feed.opportunity],
                    "combined": [_serialize_item(i) for i in feed.combined],
                    "maintenance_count": len(feed.maintenance),
                    "opportunity_count": len(feed.opportunity),
                    "total_count": len(feed.combined),
                },
                message=(
                    f"Avatar feed: {len(feed.maintenance)} maintenance, "
                    f"{len(feed.opportunity)} opportunity items"
                ),
            )

        except Exception as e:
            return error_response(
                error_code="AVATAR_FEED_FAILED",
                message=f"Failed to retrieve avatar feed: {e!s}",
                recovery_strategy="Verify client with get_client_profile. Check holdings and mandate_themes.",
                details={"client_guid": client_guid, "limit": limit},
            )

    @mcp.tool(
        name="get_top_client_news",
        description=(
            "Get top client news using graph/ephemeral data only (no LLM). "
            "USE FOR: 'What are the top 3 things to tell my client today?'. "
            "RANKED BY: Relevance to holdings/watchlist + graph relations + impact + recency. "
            "DEFAULT: Top 3 from last 24h. "
            "For LLM enrichment (why + summary), use why_it_matters_to_client. "
            "PREREQUISITE: Client must exist (use create_client first)."
        ),
    )
    def get_top_client_news(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to get top news for",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        limit: Annotated[int, Field(
            default=3,
            ge=1,
            le=10,
            description="Maximum news items to return (default: 3, max: 10)",
        )] = 3,
        time_window_hours: Annotated[int, Field(
            default=24,
            ge=1,
            le=168,
            description="How far back to search (hours). Default 24, max 168.",
        )] = 24,
        min_impact_score: Annotated[float | None, Field(
            default=None,
            ge=0.0,
            le=100.0,
            description="Minimum impact score 0-100 to filter news",
        )] = None,
        impact_tiers: Annotated[list[str] | None, Field(
            default=None,
            description="Filter by impact tiers: PLATINUM, GOLD, SILVER, BRONZE, STANDARD",
            examples=[["PLATINUM", "GOLD", "SILVER"]],
        )] = None,
        include_portfolio: Annotated[bool, Field(
            default=True,
            description="Include portfolio holdings in relevance (default: True)",
        )] = True,
        include_watchlist: Annotated[bool, Field(
            default=True,
            description="Include watchlist instruments (default: True)",
        )] = True,
        include_lateral_graph: Annotated[bool, Field(
            default=True,
            description="Include lateral graph relations like competitors/suppliers (default: True)",
        )] = True,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Get top client news using hybrid graph + semantic search."""
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            group_guids = get_group_uuids_by_names(group_names)

            if query_service is None:
                return error_response(
                    error_code="QUERY_SERVICE_UNAVAILABLE",
                    message="Query service not configured for top client news",
                    recovery_strategy="Ensure MCP server initializes QueryService and passes it to client tools.",
                    details={"client_guid": client_guid},
                )

            # Validate client exists
            client_node = graph_index.get_node(NodeLabel.CLIENT, client_guid)
            if not client_node:
                return error_response(
                    error_code="CLIENT_NOT_FOUND",
                    message=f"Client not found: {client_guid}",
                    recovery_strategy="Call list_clients to find valid client GUIDs, or create_client to create one.",
                    details={"client_guid": client_guid},
                )

            if client_node.properties.get("status") == "defunct":
                return error_response(
                    error_code="CLIENT_DEFUNCT",
                    message="Client is defunct and cannot receive news",
                    recovery_strategy="Restore the client or select an active client.",
                    details={
                        "client_guid": client_guid,
                        "defunct_at": client_node.properties.get("defunct_at"),
                        "defunct_reason": client_node.properties.get("defunct_reason"),
                    },
                )

            top_news = query_service.get_top_client_news(
                client_guid=client_guid,
                group_guids=group_guids,
                limit=limit,
                time_window_hours=time_window_hours,
                include_portfolio=include_portfolio,
                include_watchlist=include_watchlist,
                include_lateral_graph=include_lateral_graph,
                min_impact_score=min_impact_score,
                impact_tiers=impact_tiers,
            )

            resolved_min_impact = min_impact_score if min_impact_score is not None else 0.0
            missing_impact_guids = [
                article.get("document_guid")
                for article in top_news
                if article.get("impact_score") is None and article.get("document_guid")
            ]

            if missing_impact_guids:
                try:
                    with graph_index._get_session() as session:
                        result = session.run(
                            """
                            MATCH (d:Document)
                            WHERE d.guid IN $guids
                            RETURN d.guid AS guid, d.impact_score AS impact_score
                            """,
                            guids=missing_impact_guids,
                        )
                        impact_map = {record["guid"]: record["impact_score"] for record in result}

                    for article in top_news:
                        doc_guid = article.get("document_guid")
                        if doc_guid in impact_map and article.get("impact_score") is None:
                            article["impact_score"] = impact_map.get(doc_guid)
                except Exception:  # nosec B110 - silent fail for optional backfill
                    pass

            top_news = [
                article for article in top_news
                if float(article.get("impact_score") or 0.0) >= resolved_min_impact
            ][:limit]

            filters_applied = {
                "time_window_hours": time_window_hours,
                "min_impact_score": resolved_min_impact,
                "impact_tiers": impact_tiers,
                "include_portfolio": include_portfolio,
                "include_watchlist": include_watchlist,
                "include_lateral_graph": include_lateral_graph,
            }

            return success_response(
                data={
                    "articles": top_news,
                    "total_count": len(top_news),
                    "filters_applied": filters_applied,
                },
                message=f"Retrieved {len(top_news)} top news items",
            )

        except Exception as e:
            return error_response(
                error_code="TOP_NEWS_RETRIEVAL_FAILED",
                message=f"Failed to retrieve top client news: {e!s}",
                recovery_strategy="Verify client exists and QueryService is configured. Run health_check if needed.",
                details={"client_guid": client_guid, "limit": limit},
            )

    @mcp.tool(
        name="why_it_matters_to_client",
        description=(
            "LLM augmentation for a specific (client, document) pair. "
            "RETURNS: (1) <=30 words why it matters to the client, (2) <=30 words story summary. "
            "USE FOR: turning a shortlisted story into a client-ready blurb."
        ),
    )
    def why_it_matters_to_client(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        document_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the document",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Generate LLM why/summary for a single story and client."""
        try:
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            group_guids = get_group_uuids_by_names(group_names)

            if query_service is None:
                return error_response(
                    error_code="QUERY_SERVICE_UNAVAILABLE",
                    message="Query service not configured for why_it_matters_to_client",
                    recovery_strategy="Ensure MCP server initializes QueryService and passes it to client tools.",
                    details={"client_guid": client_guid, "document_guid": document_guid},
                )

            if llm_service is None:
                return error_response(
                    error_code="LLM_SERVICE_UNAVAILABLE",
                    message="LLM service not configured",
                    recovery_strategy="Configure OpenRouter key in Vault (gofr/config/api-keys/openrouter) and restart the service.",
                    details={"client_guid": client_guid, "document_guid": document_guid},
                )

            # Validate client exists and is permitted
            client_node = graph_index.get_node(NodeLabel.CLIENT, client_guid)
            if not client_node:
                return error_response(
                    error_code="CLIENT_NOT_FOUND",
                    message=f"Client not found: {client_guid}",
                    recovery_strategy="Call list_clients to find valid client GUIDs, or create_client to create one.",
                    details={"client_guid": client_guid},
                )

            if client_node.properties.get("status") == "defunct":
                return error_response(
                    error_code="CLIENT_DEFUNCT",
                    message="Client is defunct and cannot receive news",
                    recovery_strategy="Restore the client or select an active client.",
                    details={
                        "client_guid": client_guid,
                        "defunct_at": client_node.properties.get("defunct_at"),
                        "defunct_reason": client_node.properties.get("defunct_reason"),
                    },
                )

            augmentation = query_service.why_it_matters_to_client(
                client_guid=client_guid,
                document_guid=document_guid,
                group_guids=group_guids,
                llm_service=llm_service,
            )

            return success_response(
                data={
                    "client_guid": client_guid,
                    "document_guid": document_guid,
                    **augmentation,
                },
                message="Generated client-specific story augmentation",
            )
        except Exception as e:
            return error_response(
                error_code="WHY_IT_MATTERS_FAILED",
                message=f"Failed to generate why/summary: {e!s}",
                recovery_strategy="Verify client/document access and confirm LLM service is configured.",
                details={"client_guid": client_guid, "document_guid": document_guid},
            )

    @mcp.tool(
        name="add_to_portfolio",
        description=(
            "Add a stock position to a client's portfolio (actual holdings). "
            "WORKFLOW: create_client -> add_to_portfolio (+ add_to_watchlist) -> get_client_feed. "
            "USE FOR: Recording actual holdings (not just interest). 'Add AAPL to Citadel portfolio'. "
            "USES OUTPUT FROM: create_client (client_guid), list_clients (client_guid). "
            "PROVIDES INPUT TO: get_portfolio_holdings (discover holdings), get_client_feed (boosts news relevance). "
            "DIFFERENCE FROM add_to_watchlist: Portfolio = owns/holds; Watchlist = monitoring interest only. "
            "EFFECT: News about portfolio holdings gets HIGHER priority (boost) in get_client_feed results. "
            "WEIGHT FORMAT: Decimal, not percentage (0.10 = 10%, 0.05 = 5%). Weights should sum to ~1.0. "
            "PREREQUISITE: Client must exist (create_client first). Instrument created automatically. "
            "REVERSIBLE: Use remove_from_portfolio to undo."
        ),
    )
    def add_to_portfolio(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to update",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        ticker: Annotated[str, Field(
            min_length=1,
            max_length=20,
            description="Stock ticker symbol (e.g., 'AAPL', '9988.HK', '700.HK')",
            examples=["AAPL", "TSLA", "9988.HK"],
        )],
        weight: Annotated[float, Field(
            gt=0.0,
            le=1.0,
            description="Portfolio weight as decimal (0.10 = 10%, 0.05 = 5%)",
            examples=[0.10, 0.05, 0.25],
        )],
        shares: Annotated[int | None, Field(
            default=None,
            ge=1,
            description="Number of shares held (optional)",
        )] = None,
        avg_cost: Annotated[float | None, Field(
            default=None,
            gt=0.0,
            description="Average cost basis per share in USD (optional)",
        )] = None,
    ) -> ToolResponse:
        """Add a holding to client's portfolio.

        Args:
            client_guid: UUID of the client to update (36-char format)
            ticker: Stock symbol (e.g., 'AAPL', '9988.HK')
            weight: Portfolio weight as decimal (0.10 = 10%)
            shares: Number of shares (optional)
            avg_cost: Cost basis per share (optional)

        Returns:
            Confirmation with ticker, weight, shares added
        """
        try:
            # Get client's portfolio
            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)
                    RETURN p.guid AS portfolio_guid
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="PORTFOLIO_NOT_FOUND",
                        message=f"No portfolio found for client: {client_guid}",
                        recovery_strategy="Use create_client to create a client with portfolio, or verify client_guid with list_clients.",
                        details={"client_guid": client_guid},
                    )
                portfolio_guid = record["portfolio_guid"]
            
            # Resolve instrument (look up by ticker, create if missing)
            instrument_guid = _resolve_instrument_guid(graph_index, ticker)

            # Add holding
            graph_index.add_holding(
                portfolio_guid=portfolio_guid,
                instrument_guid=instrument_guid,
                weight=weight,
                shares=shares,
                avg_cost=avg_cost,
            )
            
            return success_response(
                data={
                    "ticker": ticker.upper(),
                    "weight": weight,
                    "shares": shares,
                    "avg_cost": avg_cost,
                },
                message=f"Added {ticker.upper()} to portfolio with {weight*100:.1f}% weight",
            )

        except Exception as e:
            return error_response(
                error_code="PORTFOLIO_ADD_FAILED",
                message=f"Failed to add to portfolio: {e!s}",
                recovery_strategy="Verify client with get_client_profile. Check ticker format (e.g., AAPL, 9988.HK).",
                details={"client_guid": client_guid, "ticker": ticker},
            )

    @mcp.tool(
        name="add_to_watchlist",
        description=(
            "Add a stock to a client's watchlist for monitoring (not holdings). "
            "WORKFLOW: create_client -> add_to_watchlist -> get_watchlist_items -> get_client_feed (includes watched stocks). "
            "USE FOR: Tracking stocks of interest without actual positions. "
            "INPUT FROM: create_client (client_guid) | get_client_profile (watchlist_guid). "
            "OUTPUT TO: get_watchlist_items (retrieve all) | remove_from_watchlist (delete) | get_client_feed (filtered results). "
            "EFFECT: News about watched stocks appears in get_client_feed. "
            "DIFFERENCE FROM PORTFOLIO: Watchlist = interested; Portfolio = owns. "
            "PREREQUISITE: Client must exist."
        ),
    )
    def add_to_watchlist(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to update",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        ticker: Annotated[str, Field(
            min_length=1,
            max_length=20,
            description="Stock ticker symbol to watch (e.g., 'TSLA', '700.HK')",
            examples=["TSLA", "BABA", "700.HK"],
        )],
        alert_threshold: Annotated[float | None, Field(
            default=None,
            ge=0.0,
            le=100.0,
            description="Minimum impact score 0-100 to trigger alerts for this ticker",
        )] = None,
    ) -> ToolResponse:
        """Add an instrument to client's watchlist.

        Args:
            client_guid: UUID of the client to update (36-char format)
            ticker: Stock symbol (e.g., 'TSLA', '700.HK')
            alert_threshold: Min impact score 0-100 for alerts on this ticker

        Returns:
            Confirmation with ticker added
        """
        try:
            # Get client's watchlist
            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_WATCHLIST]->(w:Watchlist)
                    RETURN w.guid AS watchlist_guid
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="WATCHLIST_NOT_FOUND",
                        message=f"No watchlist found for client: {client_guid}",
                        recovery_strategy="Use create_client to create a client with watchlist, or verify client_guid with list_clients.",
                        details={"client_guid": client_guid},
                    )
                watchlist_guid = record["watchlist_guid"]
            
            # Resolve instrument (look up by ticker, create if missing)
            instrument_guid = _resolve_instrument_guid(graph_index, ticker)

            # Add to watchlist (WATCHES relationship)
            props: dict[str, Any] = {}
            if alert_threshold is not None:
                props["alert_threshold"] = alert_threshold
                
            graph_index.create_relationship(
                RelationType.WATCHES,
                NodeLabel.WATCHLIST,
                watchlist_guid,
                NodeLabel.INSTRUMENT,
                instrument_guid,
                props,
            )
            
            return success_response(
                data={
                    "ticker": ticker.upper(),
                    "alert_threshold": alert_threshold,
                },
                message=f"Added {ticker.upper()} to watchlist",
            )

        except Exception as e:
            return error_response(
                error_code="WATCHLIST_ADD_FAILED",
                message=f"Failed to add to watchlist: {e!s}",
                recovery_strategy="Verify client with get_client_profile. Check ticker format (e.g., AAPL, 9988.HK).",
                details={"client_guid": client_guid, "ticker": ticker},
            )

    @mcp.tool(
        name="list_clients",
        description=(
            "List all clients in your group(s) with basic information. "
            "USE FOR: 'Show me all my clients' or 'Which clients do I manage?'. "
            "FILTERS: Can filter by client_type (HEDGE_FUND, LONG_ONLY, etc.), "
            "and optionally include/sort/filter by profile completeness score. "
            "RETURNS: Client GUIDs, names, types (and optional score) for further operations. "
            "NEXT STEPS: Use get_client_profile for full details on a specific client."
        ),
    )
    def list_clients(
        client_type: Annotated[str | None, Field(
            default=None,
            description="Filter: HEDGE_FUND|LONG_ONLY|QUANT|PENSION|FAMILY_OFFICE (omit for all)",
            examples=["HEDGE_FUND", "PENSION"],
        )] = None,
        include_defunct: Annotated[bool, Field(
            default=False,
            description="Include defunct clients in results (default: False)",
        )] = False,
        include_completeness_score: Annotated[bool, Field(
            default=False,
            description="Include profile completeness score in results (default: False)",
        )] = False,
        min_completeness_score: Annotated[float | None, Field(
            default=None,
            ge=0.0,
            le=1.0,
            description="Filter: minimum profile completeness score (0.0-1.0)",
        )] = None,
        sort_by_completeness: Annotated[bool, Field(
            default=False,
            description="Sort results by completeness score (desc). Requires include_completeness_score",
        )] = False,
        include_mandate_text: Annotated[bool, Field(
            default=False,
            description="Include mandate_text in results (default: False). May increase response size for large client lists.",
        )] = False,
        limit: Annotated[int, Field(
            default=50,
            ge=1,
            le=200,
            description="Maximum clients to return (default: 50, max: 200)",
        )] = 50,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """List all clients accessible to the authenticated user.

        Returns clients in groups you have permission to access.
        Anonymous users only see clients in the public group.

        Args:
            client_type: Filter by type (HEDGE_FUND, LONG_ONLY, QUANT, PENSION, FAMILY_OFFICE)
            include_completeness_score: Include completeness score in results
            min_completeness_score: Minimum completeness score to include
            sort_by_completeness: Sort results by completeness score (desc)
            include_mandate_text: Include mandate_text in results (may increase response size)
            limit: Max clients to return (default: 50)

        Returns:
            clients: List of {client_guid, name, client_type, group_guid, created_at, [mandate_text]}
            total_count: Number of clients returned
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            # Convert group names to UUIDs for storage layer
            group_guids = get_group_uuids_by_names(group_names)

            # Build query with optional type filter
            type_filter = ""
            status_filter = ""
            params: dict[str, Any] = {"limit": limit}
            
            if group_guids:
                params["group_guids"] = group_guids
                group_clause = "WHERE g.guid IN $group_guids"
            else:
                group_clause = ""  # No group filter for anonymous
                
            if client_type:
                type_filter = "AND ct.code = $client_type" if group_clause else "WHERE ct.code = $client_type"
                params["client_type"] = client_type.upper()

            if not include_defunct:
                status_filter = "AND coalesce(c.status, 'active') <> 'defunct'" if (group_clause or type_filter) else "WHERE coalesce(c.status, 'active') <> 'defunct'"

            # Build RETURN clause with optional mandate_text
            return_clause = """c.guid AS client_guid, 
                           c.name AS name,
                           ct.code AS client_type,
                           g.guid AS group_guid,
                              c.created_at AS created_at,
                              c.status AS status"""
            
            if include_mandate_text:
                return_clause += ",\n                           cp.mandate_text AS mandate_text"
                # Add optional match for profile if mandate_text needed
                profile_match = "OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)"
            else:
                profile_match = ""

            with graph_index._get_session() as session:
                result = session.run(
                    f"""
                    MATCH (c:Client)-[:IN_GROUP]->(g:Group)
                    OPTIONAL MATCH (c)-[:IS_TYPE_OF]->(ct:ClientType)
                    {profile_match}
                    {group_clause}
                    {type_filter}
                          {status_filter}
                    RETURN {return_clause}
                    ORDER BY c.name
                    LIMIT $limit
                    """,
                    **params,
                )
                
                clients = []
                for record in result:
                    client_data = {
                        "client_guid": record["client_guid"],
                        "name": record["name"],
                        "client_type": record["client_type"],
                        "group_guid": record["group_guid"],
                        "created_at": record["created_at"],
                        "status": record["status"],
                    }
                    if include_mandate_text:
                        client_data["mandate_text"] = record.get("mandate_text")
                    clients.append(client_data)

            if include_completeness_score or min_completeness_score is not None or sort_by_completeness:
                for client in clients:
                    score_data = client_service.calculate_profile_completeness(client["client_guid"])
                    client["completeness_score"] = score_data.get("score", 0.0)
                    if "error" in score_data:
                        client["completeness_error"] = score_data["error"]

                if min_completeness_score is not None:
                    clients = [
                        client
                        for client in clients
                        if client.get("completeness_score", 0.0) >= min_completeness_score
                    ]

                if sort_by_completeness:
                    clients.sort(key=lambda item: item.get("completeness_score", 0.0), reverse=True)
            
            return success_response(
                data={
                    "clients": clients,
                    "total_count": len(clients),
                    "filters_applied": {
                        "client_type": client_type,
                        "include_defunct": include_defunct,
                        "include_completeness_score": include_completeness_score,
                        "min_completeness_score": min_completeness_score,
                        "sort_by_completeness": sort_by_completeness,
                        "include_mandate_text": include_mandate_text,
                        "limit": limit,
                    },
                },
                message=f"Found {len(clients)} client(s)",
            )

        except Exception as e:
            return error_response(
                error_code="CLIENT_LIST_FAILED",
                message=f"Failed to list clients: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Ensure auth_tokens are valid.",
            )

    @mcp.tool(
        name="get_client_profile_score",
        description=(
            "Get the Client Profile Completeness Score (CPCS) for a client. "
            "USE FOR: 'How complete is this client profile?' or 'Show profile gaps'. "
            "RETURNS: Score (0-1), breakdown, and missing fields. "
            "INPUT FROM: list_clients (client_guid)."
        ),
    )
    def get_client_profile_score(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to score",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Return profile completeness score and gaps for a client."""
        try:
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            group_guids = get_group_uuids_by_names(group_names)

            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    RETURN c.guid AS client_guid, g.guid AS group_guid
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )

                if group_guids and record["group_guid"] not in group_guids:
                    return error_response(
                        error_code="ACCESS_DENIED",
                        message="You don't have access to this client's group",
                        recovery_strategy="Use list_clients to see clients you can access, or request group access.",
                        details={"client_guid": client_guid, "required_group": record["group_guid"]},
                    )

            score_data = client_service.calculate_profile_completeness(client_guid)
            if "error" in score_data:
                return error_response(
                    error_code="PROFILE_SCORE_FAILED",
                    message=score_data["error"],
                    recovery_strategy="Verify client exists and has a profile. Use get_client_profile to validate.",
                    details={"client_guid": client_guid},
                )

            return success_response(
                data={
                    "client_guid": client_guid,
                    **score_data,
                },
                message="Profile completeness score calculated",
            )

        except Exception as e:
            return error_response(
                error_code="PROFILE_SCORE_FAILED",
                message=f"Failed to calculate profile score: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Ensure auth_tokens are valid.",
                details={"client_guid": client_guid},
            )

    @mcp.tool(
        name="get_client_profile",
        description=(
            "Get complete profile and settings for a specific client. "
            "WORKFLOW: create_client -> get_client_profile -> update_client_profile | add_to_portfolio/watchlist. "
            "USE FOR: 'Show me details for client X' or 'What are Citadel's settings?'. "
            "INPUT FROM: create_client (client_guid) | list_clients (client_guid). "
            "OUTPUT TO: update_client_profile | add_to_portfolio | add_to_watchlist | get_client_feed. "
            "RETURNS: Full profile including mandate, benchmark, alert settings, "
            "portfolio_guid, watchlist_guid. "
            "PREREQUISITE: Client must exist (check with list_clients first)."
        ),
    )
    def get_client_profile(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to retrieve",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Get complete profile for a specific client.

        Returns full client details including profile settings, portfolio and
        watchlist GUIDs. Access is limited to clients in groups you can access.

        Args:
            client_guid: UUID of the client (36-char format)

        Returns:
            client_guid, name, client_type, group_guid
            profile: mandate_type, mandate_text, benchmark, horizon, esg_constrained
            settings: alert_frequency, impact_threshold
            portfolio_guid, watchlist_guid, created_at
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            # Convert group names to UUIDs for storage layer
            group_guids = get_group_uuids_by_names(group_names)

            with graph_index._get_session() as session:
                # Get client with all related data in one query
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    OPTIONAL MATCH (c)-[:IS_TYPE_OF]->(ct:ClientType)
                    OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
                    OPTIONAL MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)
                    OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)
                    OPTIONAL MATCH (cp)-[:BENCHMARKED_TO]->(b:Instrument)
                    RETURN c.guid AS client_guid,
                           c.name AS name,
                           c.alert_frequency AS alert_frequency,
                           c.impact_threshold AS impact_threshold,
                           c.status AS status,
                           c.defunct_at AS defunct_at,
                           c.defunct_reason AS defunct_reason,
                           c.created_at AS created_at,
                           ct.code AS client_type,
                           g.guid AS group_guid,
                           cp.guid AS profile_guid,
                           cp.mandate_type AS mandate_type,
                           cp.mandate_text AS mandate_text,
                           cp.mandate_themes AS mandate_themes,
                           cp.horizon AS horizon,
                           cp.esg_constrained AS esg_constrained,
                           cp.restrictions AS restrictions_json,
                           b.ticker AS benchmark,
                           p.guid AS portfolio_guid,
                           w.guid AS watchlist_guid
                    """,
                    client_guid=client_guid,
                )
                
                record = result.single()
                if not record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )
                
                # Check group access
                if group_guids and record["group_guid"] not in group_guids:
                    return error_response(
                        error_code="ACCESS_DENIED",
                        message="You don't have access to this client's group",
                        recovery_strategy="Use list_clients to see clients you can access, or request group access.",
                        details={"client_guid": client_guid, "required_group": record["group_guid"]},
                    )
                
                # Parse restrictions JSON if present
                restrictions_data = None
                restrictions_json = record.get("restrictions_json")
                if restrictions_json:
                    try:
                        restrictions_data = json.loads(restrictions_json)
                    except json.JSONDecodeError:
                        restrictions_data = None
            
            return success_response(
                data={
                    "client_guid": record["client_guid"],
                    "name": record["name"],
                    "client_type": record["client_type"],
                    "group_guid": record["group_guid"],
                    "status": record["status"],
                    "defunct_at": record["defunct_at"],
                    "defunct_reason": record["defunct_reason"],
                    "profile": {
                        "guid": record["profile_guid"],
                        "mandate_type": record["mandate_type"],
                        "mandate_text": record["mandate_text"],
                        "mandate_themes": record["mandate_themes"],
                        "benchmark": record["benchmark"],
                        "horizon": record["horizon"],
                        "esg_constrained": record["esg_constrained"],
                        "restrictions": restrictions_data,
                    },
                    "settings": {
                        "alert_frequency": record["alert_frequency"],
                        "impact_threshold": record["impact_threshold"],
                    },
                    "portfolio_guid": record["portfolio_guid"],
                    "watchlist_guid": record["watchlist_guid"],
                    "created_at": record["created_at"],
                },
                message=f"Retrieved profile for '{record['name']}'",
            )

        except Exception as e:
            return error_response(
                error_code="PROFILE_RETRIEVAL_FAILED",
                message=f"Failed to get client profile: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Call list_clients to confirm client exists.",
                details={"client_guid": client_guid},
            )

    @mcp.tool(
        name="get_portfolio_holdings",
        description=(
            "List all holdings in a client's portfolio with weights and positions. "
            "WORKFLOW: create_client -> add_to_portfolio -> get_portfolio_holdings -> remove_from_portfolio. "
            "USE FOR: 'What stocks does Citadel hold?' or 'Show portfolio for client X'. "
            "USES OUTPUT FROM: add_to_portfolio (holdings added) | create_client (portfolio created). "
            "PROVIDES INPUT TO: remove_from_portfolio (ticker list) | get_client_feed (portfolio context). "
            "RETURNS: Tickers, weights (as decimal), shares, avg_cost, added_at. "
            "WEIGHT INTERPRETATION: Sum of all weights should be ~1.0 (100%). Each holding shows % allocation. "
            "PREREQUISITE: Client must exist with holdings (call add_to_portfolio first). "
            "TIP: Use this to verify portfolio before removing positions with remove_from_portfolio."
        ),
    )
    def get_portfolio_holdings(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client whose portfolio to retrieve",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Get all holdings in a client's portfolio.

        Returns all positions with weights, shares, and cost basis.
        Access is limited to clients in groups you can access.

        Args:
            client_guid: UUID of the client (36-char format)

        Returns:
            portfolio_guid: Portfolio identifier
            holdings: List of {ticker, weight, shares, avg_cost, added_at}
            total_weight: Sum of all weights (should be ~1.0)
            holding_count: Number of positions
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            # Convert group names to UUIDs for storage layer
            group_guids = get_group_uuids_by_names(group_names)

            with graph_index._get_session() as session:
                # First verify client exists and user has access
                access_check = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    RETURN g.guid AS group_guid, c.name AS client_name
                    """,
                    client_guid=client_guid,
                )
                access_record = access_check.single()
                
                if not access_record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )
                
                if group_guids and access_record["group_guid"] not in group_guids:
                    return error_response(
                        error_code="ACCESS_DENIED",
                        message="You don't have access to this client's group",
                        recovery_strategy="Use list_clients to see clients you can access.",
                        details={"client_guid": client_guid},
                    )

                # Get portfolio holdings
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)
                    OPTIONAL MATCH (p)-[h:HOLDS]->(i:Instrument)
                    RETURN p.guid AS portfolio_guid,
                           i.ticker AS ticker,
                           i.name AS instrument_name,
                           h.weight AS weight,
                           h.shares AS shares,
                           h.avg_cost AS avg_cost,
                           h.added_at AS added_at
                    ORDER BY coalesce(h.weight, -1) DESC
                    """,
                    client_guid=client_guid,
                )
                
                holdings = []
                portfolio_guid = None
                total_weight = 0.0
                
                for record in result:
                    portfolio_guid = record["portfolio_guid"]
                    if record["ticker"]:  # Has actual holdings
                        weight = record["weight"] or 0.0
                        total_weight += weight
                        holdings.append({
                            "ticker": record["ticker"],
                            "instrument_name": record["instrument_name"],
                            "weight": weight,
                            "weight_pct": f"{weight * 100:.1f}%",
                            "shares": record["shares"],
                            "avg_cost": record["avg_cost"],
                            "added_at": record["added_at"],
                        })
                
                if not portfolio_guid:
                    return error_response(
                        error_code="PORTFOLIO_NOT_FOUND",
                        message=f"No portfolio found for client: {client_guid}",
                        recovery_strategy="Verify client with get_client_profile. Portfolio created automatically with create_client.",
                        details={"client_guid": client_guid},
                    )
            
            return success_response(
                data={
                    "client_guid": client_guid,
                    "client_name": access_record["client_name"],
                    "portfolio_guid": portfolio_guid,
                    "holdings": holdings,
                    "total_weight": round(total_weight, 4),
                    "total_weight_pct": f"{total_weight * 100:.1f}%",
                    "holding_count": len(holdings),
                },
                message=f"Retrieved {len(holdings)} holding(s) for '{access_record['client_name']}'",
            )

        except Exception as e:
            return error_response(
                error_code="HOLDINGS_RETRIEVAL_FAILED",
                message=f"Failed to get portfolio holdings: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Call get_client_profile to confirm client exists.",
                details={"client_guid": client_guid},
            )

    @mcp.tool(
        name="get_watchlist_items",
        description=(
            "List all stocks on a client's watchlist (monitoring without positions). "
            "WORKFLOW: create_client -> add_to_watchlist -> get_watchlist_items -> remove_from_watchlist. "
            "USE FOR: 'What stocks is Citadel watching?' or 'Show watchlist for client X'. "
            "USES OUTPUT FROM: add_to_watchlist (items added) | create_client (watchlist created). "
            "PROVIDES INPUT TO: remove_from_watchlist (ticker list) | get_client_feed (watchlist context). "
            "DIFFERENCE FROM get_portfolio_holdings: Watchlist = interested (monitoring); Portfolio = actually owns. "
            "EFFECT: Watchlist stocks appear in get_client_feed but with LOWER priority than portfolio holdings. "
            "RETURNS: Tickers and alert thresholds for monitored stocks. "
            "PREREQUISITE: Client must exist with items on watchlist (call add_to_watchlist first). "
            "TIP: Use this to verify watchlist before removing items with remove_from_watchlist."
        ),
    )
    def get_watchlist_items(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client whose watchlist to retrieve",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Get all items on a client's watchlist.

        Returns all watched instruments with alert thresholds.
        Access is limited to clients in groups you can access.

        Args:
            client_guid: UUID of the client (36-char format)

        Returns:
            watchlist_guid: Watchlist identifier
            items: List of {ticker, alert_threshold, added_at}
            item_count: Number of watched stocks
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            # Convert group names to UUIDs for storage layer
            group_guids = get_group_uuids_by_names(group_names)

            with graph_index._get_session() as session:
                # First verify client exists and user has access
                access_check = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    RETURN g.guid AS group_guid, c.name AS client_name
                    """,
                    client_guid=client_guid,
                )
                access_record = access_check.single()
                
                if not access_record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )
                
                if group_guids and access_record["group_guid"] not in group_guids:
                    return error_response(
                        error_code="ACCESS_DENIED",
                        message="You don't have access to this client's group",
                        recovery_strategy="Use list_clients to see clients you can access.",
                        details={"client_guid": client_guid},
                    )

                # Get watchlist items
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_WATCHLIST]->(w:Watchlist)
                    OPTIONAL MATCH (w)-[r:WATCHES]->(i:Instrument)
                    RETURN w.guid AS watchlist_guid,
                           w.name AS watchlist_name,
                           i.ticker AS ticker,
                           i.name AS instrument_name,
                           r.alert_threshold AS alert_threshold,
                           r.added_at AS added_at
                    ORDER BY i.ticker
                    """,
                    client_guid=client_guid,
                )
                
                items = []
                watchlist_guid = None
                watchlist_name = None
                
                for record in result:
                    watchlist_guid = record["watchlist_guid"]
                    watchlist_name = record["watchlist_name"]
                    if record["ticker"]:  # Has actual items
                        items.append({
                            "ticker": record["ticker"],
                            "instrument_name": record["instrument_name"],
                            "alert_threshold": record["alert_threshold"],
                            "added_at": record["added_at"],
                        })
                
                if not watchlist_guid:
                    return error_response(
                        error_code="WATCHLIST_NOT_FOUND",
                        message=f"No watchlist found for client: {client_guid}",
                        recovery_strategy="Verify client with get_client_profile. Watchlist created automatically with create_client.",
                        details={"client_guid": client_guid},
                    )
            
            return success_response(
                data={
                    "client_guid": client_guid,
                    "client_name": access_record["client_name"],
                    "watchlist_guid": watchlist_guid,
                    "watchlist_name": watchlist_name,
                    "items": items,
                    "item_count": len(items),
                },
                message=f"Retrieved {len(items)} watched stock(s) for '{access_record['client_name']}'",
            )

        except Exception as e:
            return error_response(
                error_code="WATCHLIST_RETRIEVAL_FAILED",
                message=f"Failed to get watchlist items: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Call get_client_profile to confirm client exists.",
                details={"client_guid": client_guid},
            )

    @mcp.tool(
        name="update_client_profile",
        description=(
            "Update a client's profile settings (alert frequency, thresholds, investment style, mandate text). "
            "WORKFLOW: create_client -> get_client_profile -> update_client_profile -> get_client_feed. "
            "USE FOR: 'Change Citadel to daily alerts' or 'Set impact threshold to 70', 'Change mandate to equity_long_short', 'Add mandate text description'. "
            "USES OUTPUT FROM: create_client (client_guid) | get_client_profile (current settings). "
            "PROVIDES INPUT TO: get_client_feed (alert settings) | get_client_profile (returns updated). "
            "PARTIAL UPDATE: Only provide fields you want to change. Omitted fields keep current values. "
            "PREREQUISITE CHAIN: create_client -> get_client_profile (see current) -> update_client_profile (make changes). "
            "RETURNS: Updated profile with all current settings. "
            "ALERT FREQUENCY: realtime|hourly|daily|weekly. Affects notification frequency. "
            "IMPACT_THRESHOLD: 0-100. Higher = fewer alerts (only major news). 70+ for executives, 50 for analysts, 30 for researchers. "
            "MANDATE_TEXT: Free-text fund mandate description (0-5000 chars). Contributes 17.5% to CPCS. Will enhance document search. "
            "REVERSIBLE: Keep calling update_client_profile with different values."
        ),
    )
    def update_client_profile(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to update",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        alert_frequency: Annotated[str | None, Field(
            default=None,
            description="Alerts: realtime|hourly|daily|weekly (omit to keep)",
            examples=["realtime", "daily"],
        )] = None,
        impact_threshold: Annotated[float | None, Field(
            default=None,
            ge=0.0,
            le=100.0,
            description=(
                "Minimum impact score 0-100 for alerts. "
                "Higher = fewer alerts (only major news). Lower = more alerts. "
                "Typical: 70+ for executives, 50 for analysts, 30 for researchers."
            ),
        )] = None,
        mandate_type: Annotated[str | None, Field(
            default=None,
            description=(
                "Investment mandate style: equity_long_short, global_macro, event_driven, "
                "relative_value, fixed_income, multi_strategy. Leave empty to keep current."
            ),
        )] = None,
        mandate_text: Annotated[str | None, Field(
            default=None,
            max_length=5000,
            description=(
                "Free-text fund mandate description (0-5000 chars). Provides detailed investment guidelines, "
                "restrictions, objectives beyond categorical mandate_type. Empty string clears field. "
                "Omit to keep current value. Contributes 17.5% to CPCS. Will be used to enhance document search."
            ),
            examples=["Our fund focuses on US technology stocks with strong ESG ratings and sustainable business models."],
        )] = None,
        benchmark: Annotated[str | None, Field(
            default=None,
            description=(
                "Benchmark ticker symbol (e.g., 'SPY', 'QQQ', 'IWM'). "
                "Used to compare performance. Leave empty to keep current."
            ),
        )] = None,
        horizon: Annotated[str | None, Field(
            default=None,
            description="Horizon: short (<1mo)|medium (1-6mo)|long (>6mo) (omit to keep)",
            examples=["short", "long"],
        )] = None,
        esg_constrained: Annotated[bool | None, Field(
            default=None,
            description=(
                "Apply ESG filters to news feed. True = exclude non-ESG compliant news. "
                "Leave empty to keep current."
            ),
        )] = None,
        restrictions: Annotated[dict[str, Any] | None, Field(
            default=None,
            description=(
                "Full replacement for ESG & compliance restrictions object. "
                "Categories: ethical_sector, impact_sustainability, legal_regulatory, operational_risk, tax_accounting. "
                "Pass empty dict {} to clear restrictions. Omit to keep current."
            ),
        )] = None,
        mandate_themes: Annotated[list[str] | None, Field(
            default=None,
            description=(
                "List of theme tags from controlled vocabulary (e.g., ['semiconductor', 'ev_battery', 'ai']). "
                "Used by Avatar Feed for opportunity matching. Pass empty list [] to clear. Omit to keep current. "
                "Valid themes: ai, semiconductor, ev_battery, supply_chain, m_and_a, rates, fx, credit, esg, "
                "energy_transition, geopolitical, japan, china, india, korea, fintech, biotech, real_estate, "
                "commodities, consumer, defense, cloud, cybersecurity, autonomous_vehicles, blockchain."
            ),
            examples=[["semiconductor", "ai", "japan"], ["ev_battery", "china", "supply_chain"]],
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Update client profile settings.

        Performs partial updates - only provided fields are changed.
        Access is limited to clients in groups you can access.

        Args:
            client_guid: UUID of the client (36-char format)
            alert_frequency: realtime, hourly, daily, or weekly
            impact_threshold: Min impact score 0-100 for alerts
            mandate_type: Investment style
            mandate_text: Free-text mandate description (0-5000 chars, empty string clears)
            mandate_themes: Theme tags for opportunity matching (empty list clears)
            benchmark: Benchmark ticker
            horizon: short, medium, or long
            esg_constrained: Apply ESG filters
            restrictions: Full replacement for ESG restrictions object (empty dict clears)

        Returns:
            Updated profile with all current settings
            changes: List of fields that were updated
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            # Convert group names to UUIDs for storage layer
            group_guids = get_group_uuids_by_names(group_names)

            # Check if any update fields provided
            updates_client: dict[str, Any] = {}
            updates_profile: dict[str, Any] = {}
            changes: list[str] = []
            
            if alert_frequency is not None:
                valid_frequencies = ["realtime", "hourly", "daily", "weekly"]
                if alert_frequency.lower() not in valid_frequencies:
                    return error_response(
                        error_code="INVALID_ALERT_FREQUENCY",
                        message=f"Invalid alert_frequency: {alert_frequency}",
                        recovery_strategy="Valid values: realtime|hourly|daily|weekly",
                        details={"provided": alert_frequency, "valid": valid_frequencies},
                    )
                updates_client["alert_frequency"] = alert_frequency.lower()
                changes.append("alert_frequency")
                
            if impact_threshold is not None:
                updates_client["impact_threshold"] = impact_threshold
                changes.append("impact_threshold")
                
            if mandate_type is not None:
                updates_profile["mandate_type"] = mandate_type
                changes.append("mandate_type")
            
            if mandate_text is not None:
                # Explicit None check - empty string is valid (clears field)
                if len(mandate_text) > 5000:
                    return error_response(
                        error_code="MANDATE_TEXT_TOO_LONG",
                        message=f"Mandate text exceeds 5000 character limit: {len(mandate_text)} chars",
                        recovery_strategy="Shorten the text to 5000 characters or less.",
                        details={"length": len(mandate_text), "max_length": 5000},
                    )
                # Store stripped text (empty string clears the field)
                stripped_text = mandate_text.strip()
                updates_profile["mandate_text"] = stripped_text
                changes.append("mandate_text")
                
                # Auto-enrich mandate_themes from mandate_text (LLM at update-time only)
                # Only if themes weren't explicitly provided and text is non-empty
                if mandate_themes is None and stripped_text:
                    from app.services.mandate_enrichment import extract_themes_from_mandate
                    from app.services.llm_service import create_llm_service
                    
                    try:
                        with create_llm_service() as llm_service:
                            enrichment_result = extract_themes_from_mandate(
                                stripped_text, llm_service
                            )
                            if enrichment_result.success and enrichment_result.themes:
                                updates_profile["mandate_themes"] = enrichment_result.themes
                                changes.append("mandate_themes (auto-enriched)")
                    except Exception:  # nosec B110 - enrichment failure is non-fatal; themes can be set manually
                        pass
                
            if horizon is not None:
                valid_horizons = ["short", "medium", "long"]
                if horizon.lower() not in valid_horizons:
                    return error_response(
                        error_code="INVALID_HORIZON",
                        message=f"Invalid horizon: {horizon}",
                        recovery_strategy="Valid values: short (<1mo)|medium (1-6mo)|long (>6mo)",
                        details={"provided": horizon, "valid": valid_horizons},
                    )
                updates_profile["horizon"] = horizon.lower()
                changes.append("horizon")
                
            if esg_constrained is not None:
                updates_profile["esg_constrained"] = esg_constrained
                changes.append("esg_constrained")

            # Handle restrictions update
            validated_restrictions: ClientRestrictions | None = None
            if restrictions is not None:
                if restrictions == {}:
                    # Empty dict clears restrictions
                    updates_profile["restrictions"] = ""
                    changes.append("restrictions")
                else:
                    try:
                        validated_restrictions = ClientRestrictions(**restrictions)
                        updates_profile["restrictions"] = validated_restrictions.model_dump_json()
                        changes.append("restrictions")
                        # Auto-enable esg_constrained if exclusions are defined
                        if validated_restrictions.has_exclusions() and esg_constrained is None:
                            updates_profile["esg_constrained"] = True
                            if "esg_constrained" not in changes:
                                changes.append("esg_constrained")
                    except ValidationError as ve:
                        return error_response(
                            error_code="INVALID_RESTRICTIONS",
                            message="Invalid restrictions schema",
                            recovery_strategy="Check restrictions structure against documented schema.",
                            details={"validation_errors": ve.errors()},
                        )

            # Handle mandate_themes update (list stored as JSON)
            if mandate_themes is not None:
                # Validate themes against controlled vocabulary
                from app.models.themes import VALID_THEMES as valid_themes
                invalid_themes = [t for t in mandate_themes if t.lower() not in valid_themes]
                if invalid_themes:
                    return error_response(
                        error_code="INVALID_MANDATE_THEMES",
                        message=f"Invalid theme(s): {', '.join(invalid_themes)}",
                        recovery_strategy="Use themes from controlled vocabulary.",
                        details={"invalid": invalid_themes, "valid": sorted(valid_themes)},
                    )
                # Normalize and store as JSON array (or Neo4j list)
                normalized = [t.lower().strip() for t in mandate_themes]
                updates_profile["mandate_themes"] = normalized
                changes.append("mandate_themes")

            if not changes and benchmark is None:
                return error_response(
                    error_code="NO_UPDATES_PROVIDED",
                    message="No update fields provided",
                    recovery_strategy="Provide at least one field: alert_frequency, impact_threshold, mandate_type, mandate_text, horizon, benchmark, esg_constrained, restrictions.",
                )

            with graph_index._get_session() as session:
                # Verify client exists and user has access
                access_check = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
                    RETURN g.guid AS group_guid, c.name AS client_name, cp.guid AS profile_guid
                    """,
                    client_guid=client_guid,
                )
                access_record = access_check.single()
                
                if not access_record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )
                
                if group_guids and access_record["group_guid"] not in group_guids:
                    return error_response(
                        error_code="ACCESS_DENIED",
                        message="You don't have access to this client's group",
                        recovery_strategy="Use list_clients to see clients you can access.",
                        details={"client_guid": client_guid},
                    )

                # Update client node properties
                if updates_client:
                    set_clauses = ", ".join([f"c.{k} = ${k}" for k in updates_client])
                    query = f"""  
                        MATCH (c:Client {{guid: $client_guid}})
                        SET {set_clauses}
                        """  # type: ignore[assignment]
                    session.run(
                        query,  # type: ignore[arg-type]
                        client_guid=client_guid,
                        **updates_client,
                    )

                # Update profile node properties
                if updates_profile:
                    set_clauses = ", ".join([f"cp.{k} = ${k}" for k in updates_profile])
                    query = f"""
                        MATCH (c:Client {{guid: $client_guid}})-[:HAS_PROFILE]->(cp:ClientProfile)
                        SET {set_clauses}
                        """  # type: ignore[assignment]
                    session.run(
                        query,  # type: ignore[arg-type]
                        client_guid=client_guid,
                        **updates_profile,
                    )

                # Handle benchmark update (creates/updates relationship)
                if benchmark is not None:
                    changes.append("benchmark")
                    # Resolve instrument (look up by ticker, create if missing)
                    instrument_guid = _resolve_instrument_guid(
                        graph_index, benchmark, instrument_type="ETF",
                    )

                    # Remove old benchmark relationship and create new one
                    session.run(
                        """
                        MATCH (c:Client {guid: $client_guid})-[:HAS_PROFILE]->(cp:ClientProfile)
                        OPTIONAL MATCH (cp)-[r:BENCHMARKED_TO]->()
                        DELETE r
                        WITH cp
                        MATCH (i:Instrument {guid: $instrument_guid})
                        CREATE (cp)-[:BENCHMARKED_TO]->(i)
                        """,
                        client_guid=client_guid,
                        instrument_guid=instrument_guid,
                    )

                # Fetch updated profile to return
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    OPTIONAL MATCH (c)-[:IS_TYPE_OF]->(ct:ClientType)
                    OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
                    OPTIONAL MATCH (cp)-[:BENCHMARKED_TO]->(b:Instrument)
                    RETURN c.guid AS client_guid,
                           c.name AS name,
                           c.alert_frequency AS alert_frequency,
                           c.impact_threshold AS impact_threshold,
                           ct.code AS client_type,
                           g.guid AS group_guid,
                           cp.mandate_type AS mandate_type,
                           cp.mandate_text AS mandate_text,
                           cp.mandate_themes AS mandate_themes,
                           cp.horizon AS horizon,
                           cp.esg_constrained AS esg_constrained,
                           b.ticker AS benchmark
                    """,
                    client_guid=client_guid,
                )
                updated = result.single()
                
                if updated is None:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found after update: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )

            return success_response(
                data={
                    "client_guid": updated["client_guid"],
                    "name": updated["name"],
                    "client_type": updated["client_type"],
                    "group_guid": updated["group_guid"],
                    "profile": {
                        "mandate_type": updated["mandate_type"],
                        "mandate_text": updated["mandate_text"],
                        "mandate_themes": updated["mandate_themes"],
                        "benchmark": updated["benchmark"],
                        "horizon": updated["horizon"],
                        "esg_constrained": updated["esg_constrained"],
                    },
                    "settings": {
                        "alert_frequency": updated["alert_frequency"],
                        "impact_threshold": updated["impact_threshold"],
                    },
                    "changes": changes,
                },
                message=f"Updated {len(changes)} field(s) for '{updated['name']}': {', '.join(changes)}",
            )

        except Exception as e:
            attempted = changes if "changes" in locals() else []  # type: ignore[possibly-undefined]
            return error_response(
                error_code="UPDATE_PROFILE_FAILED",
                message=f"Failed to update client profile: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Call get_client_profile to see current values.",
                details={"client_guid": client_guid, "attempted_changes": attempted},
            )

    @mcp.tool(
        name="remove_from_portfolio",
        description=(
            "Remove a stock position from a client's portfolio. "
            "WORKFLOW: add_to_portfolio -> get_portfolio_holdings -> remove_from_portfolio (confirm with next get_portfolio_holdings). "
            "USE FOR: 'Remove AAPL from Citadel portfolio' or 'Client sold their TSLA position'. "
            "USES OUTPUT FROM: get_portfolio_holdings (holdings list to remove) | create_client (portfolio exists). "
            "PROVIDES INPUT TO: get_portfolio_holdings (verify removal) | get_client_feed (news ranking changes). "
            "EFFECT: Stock no longer boosts news relevance in get_client_feed. "
            "PREREQUISITE: Holding must exist (check with get_portfolio_holdings first). "
            "REVERSIBLE: Can add back later with add_to_portfolio. "
            "TIP: Use get_portfolio_holdings first to see current positions and verify ticker exists."
        ),
    )
    def remove_from_portfolio(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client whose portfolio to modify",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        ticker: Annotated[str, Field(
            min_length=1,
            max_length=20,
            description="Stock ticker symbol to remove (e.g., 'AAPL', '9988.HK')",
            examples=["AAPL", "TSLA", "9988.HK"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Remove a holding from client's portfolio.

        Deletes the HOLDS relationship between portfolio and instrument.
        The instrument itself is not deleted.

        Args:
            client_guid: UUID of the client (36-char format)
            ticker: Stock symbol to remove (e.g., 'AAPL')

        Returns:
            Confirmation with ticker removed and remaining holding count
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            # Convert group names to UUIDs for storage layer
            group_guids = get_group_uuids_by_names(group_names)

            with graph_index._get_session() as session:
                # Verify client exists and user has access
                access_check = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    RETURN g.guid AS group_guid, c.name AS client_name
                    """,
                    client_guid=client_guid,
                )
                access_record = access_check.single()
                
                if not access_record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )
                
                if group_guids and access_record["group_guid"] not in group_guids:
                    return error_response(
                        error_code="ACCESS_DENIED",
                        message="You don't have access to this client's group",
                        recovery_strategy="Use list_clients to see clients you can access.",
                        details={"client_guid": client_guid},
                    )

                # Try to delete the holding relationship
                ticker_upper = ticker.upper()
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)
                    MATCH (p)-[h:HOLDS]->(i:Instrument)
                    WHERE i.ticker = $ticker
                    DELETE h
                    RETURN count(h) AS deleted
                    """,
                    client_guid=client_guid,
                    ticker=ticker_upper,
                )
                record = result.single()
                deleted_count = record["deleted"] if record else 0

                if deleted_count == 0:
                    return error_response(
                        error_code="HOLDING_NOT_FOUND",
                        message=f"Ticker {ticker_upper} not found in portfolio",
                        recovery_strategy="Call get_portfolio_holdings to see current positions. Use add_to_portfolio if ticker was never added.",
                        details={"client_guid": client_guid, "ticker": ticker_upper},
                    )

                # Get remaining holdings count
                count_result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_PORTFOLIO]->(p:Portfolio)
                    OPTIONAL MATCH (p)-[h:HOLDS]->()
                    RETURN count(h) AS remaining
                    """,
                    client_guid=client_guid,
                )
                count_record = count_result.single()
                remaining = count_record["remaining"] if count_record else 0

            return success_response(
                data={
                    "client_guid": client_guid,
                    "client_name": access_record["client_name"],
                    "ticker_removed": ticker_upper,
                    "remaining_holdings": remaining,
                },
                message=f"Removed {ticker_upper} from '{access_record['client_name']}' portfolio ({remaining} holdings remain)",
            )

        except Exception as e:
            return error_response(
                error_code="PORTFOLIO_REMOVE_FAILED",
                message=f"Failed to remove from portfolio: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Call get_portfolio_holdings to verify position exists.",
                details={"client_guid": client_guid, "ticker": ticker},
            )

    @mcp.tool(
        name="remove_from_watchlist",
        description=(
            "Stop watching a stock (remove from client's watchlist). "
            "WORKFLOW: add_to_watchlist -> get_watchlist_items -> remove_from_watchlist (confirm with next get_watchlist_items). "
            "USE FOR: 'Stop watching TSLA for Citadel' or 'Remove BABA from watchlist'. "
            "USES OUTPUT FROM: get_watchlist_items (watchlist items to remove) | create_client (watchlist exists). "
            "PROVIDES INPUT TO: get_watchlist_items (verify removal) | get_client_feed (watchlist context changes). "
            "DIFFERENCE FROM remove_from_portfolio: Watchlist = monitoring interest; Portfolio = actual holdings. "
            "EFFECT: Stock no longer appears in get_client_feed watchlist results. "
            "PREREQUISITE: Item must exist on watchlist (check with get_watchlist_items first). "
            "REVERSIBLE: Can add back later with add_to_watchlist. "
            "TIP: Use get_watchlist_items first to see current watched stocks."
        ),
    )
    def remove_from_watchlist(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client whose watchlist to modify",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        ticker: Annotated[str, Field(
            min_length=1,
            max_length=20,
            description="Stock ticker symbol to stop watching (e.g., 'TSLA', '700.HK')",
            examples=["TSLA", "BABA", "700.HK"],
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Remove an instrument from client's watchlist.

        Deletes the WATCHES relationship between watchlist and instrument.
        The instrument itself is not deleted.

        Args:
            client_guid: UUID of the client (36-char format)
            ticker: Stock symbol to stop watching (e.g., 'TSLA')

        Returns:
            Confirmation with ticker removed and remaining watch count
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_names = resolve_permitted_groups(auth_tokens=auth_tokens)
            # Convert group names to UUIDs for storage layer
            group_guids = get_group_uuids_by_names(group_names)

            with graph_index._get_session() as session:
                # Verify client exists and user has access
                access_check = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:IN_GROUP]->(g:Group)
                    RETURN g.guid AS group_guid, c.name AS client_name
                    """,
                    client_guid=client_guid,
                )
                access_record = access_check.single()
                
                if not access_record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )
                
                if group_guids and access_record["group_guid"] not in group_guids:
                    return error_response(
                        error_code="ACCESS_DENIED",
                        message="You don't have access to this client's group",
                        recovery_strategy="Use list_clients to see clients you can access.",
                        details={"client_guid": client_guid},
                    )

                # Try to delete the watches relationship
                ticker_upper = ticker.upper()
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_WATCHLIST]->(w:Watchlist)
                    MATCH (w)-[r:WATCHES]->(i:Instrument)
                    WHERE i.ticker = $ticker
                    DELETE r
                    RETURN count(r) AS deleted
                    """,
                    client_guid=client_guid,
                    ticker=ticker_upper,
                )
                record = result.single()
                deleted_count = record["deleted"] if record else 0

                if deleted_count == 0:
                    return error_response(
                        error_code="WATCH_NOT_FOUND",
                        message=f"Ticker {ticker_upper} not found in watchlist",
                        recovery_strategy="Call get_watchlist_items to see current watched stocks. Use add_to_watchlist if ticker was never added.",
                        details={"client_guid": client_guid, "ticker": ticker_upper},
                    )

                # Get remaining watch count
                count_result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})-[:HAS_WATCHLIST]->(w:Watchlist)
                    OPTIONAL MATCH (w)-[r:WATCHES]->()
                    RETURN count(r) AS remaining
                    """,
                    client_guid=client_guid,
                )
                count_record = count_result.single()
                remaining = count_record["remaining"] if count_record else 0

            return success_response(
                data={
                    "client_guid": client_guid,
                    "client_name": access_record["client_name"],
                    "ticker_removed": ticker_upper,
                    "remaining_watched": remaining,
                },
                message=f"Stopped watching {ticker_upper} for '{access_record['client_name']}' ({remaining} stocks still watched)",
            )

        except Exception as e:
            return error_response(
                error_code="WATCHLIST_REMOVE_FAILED",
                message=f"Failed to remove from watchlist: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Call get_watchlist_items to verify ticker is watched.",
                details={"client_guid": client_guid, "ticker": ticker},
            )

    @mcp.tool(
        name="defunct_client",
        description=(
            "Soft-delete a client by marking status=defunct and disabling alerts. "
            "ADMIN ONLY. USE FOR: retired clients or migrations. "
            "RETURNS: client_guid, status, defunct_at."
        ),
    )
    def defunct_client(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to defunct",
        )],
        reason: Annotated[str | None, Field(
            default=None,
            description="Reason for defuncting",
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (admin required)",
        )] = None,
    ) -> ToolResponse:
        """Soft-delete a client."""
        from datetime import datetime

        is_admin, groups = _require_admin_group(auth_tokens)
        if not is_admin:
            return error_response(
                error_code="ACCESS_DENIED",
                message="Admin access required to defunct clients",
                recovery_strategy="Use an admin token or request admin access.",
                details={"permitted_groups": groups},
            )

        try:
            defunct_at = datetime.utcnow().isoformat()
            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})
                    SET c.status = 'defunct',
                        c.defunct_at = $defunct_at,
                        c.defunct_reason = $reason,
                        c.alert_frequency = 'weekly',
                        c.impact_threshold = 100
                    RETURN c.guid AS client_guid, c.status AS status, c.defunct_at AS defunct_at
                    """,
                    client_guid=client_guid,
                    defunct_at=defunct_at,
                    reason=reason,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )

            return success_response(
                data={
                    "client_guid": record["client_guid"],
                    "status": record["status"],
                    "defunct_at": record["defunct_at"],
                    "defunct_reason": reason,
                },
                message=f"Client defuncted: {client_guid}",
            )
        except Exception as e:
            return error_response(
                error_code="DEFUNCT_FAILED",
                message=f"Failed to defunct client: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j connectivity.",
                details={"client_guid": client_guid},
            )

    @mcp.tool(
        name="restore_client",
        description=(
            "Restore a defunct client to active status. ADMIN ONLY. "
            "RETURNS: client_guid, status."
        ),
    )
    def restore_client(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to restore",
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (admin required)",
        )] = None,
    ) -> ToolResponse:
        """Restore a defunct client."""
        is_admin, groups = _require_admin_group(auth_tokens)
        if not is_admin:
            return error_response(
                error_code="ACCESS_DENIED",
                message="Admin access required to restore clients",
                recovery_strategy="Use an admin token or request admin access.",
                details={"permitted_groups": groups},
            )

        try:
            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})
                    SET c.status = 'active'
                    REMOVE c.defunct_at
                    REMOVE c.defunct_reason
                    RETURN c.guid AS client_guid, c.status AS status
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )

            return success_response(
                data={
                    "client_guid": record["client_guid"],
                    "status": record["status"],
                },
                message=f"Client restored: {client_guid}",
            )
        except Exception as e:
            return error_response(
                error_code="RESTORE_FAILED",
                message=f"Failed to restore client: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j connectivity.",
                details={"client_guid": client_guid},
            )

    @mcp.tool(
        name="move_client_group",
        description=(
            "Move a client (and portfolio/watchlist) to a different group. ADMIN ONLY."
        ),
    )
    def move_client_group(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to move",
        )],
        target_group: Annotated[str, Field(
            description="Target group name (e.g., 'us-sales')",
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (admin required)",
        )] = None,
    ) -> ToolResponse:
        """Move a client and its related nodes to a new group."""
        is_admin, groups = _require_admin_group(auth_tokens)
        if not is_admin:
            return error_response(
                error_code="ACCESS_DENIED",
                message="Admin access required to move clients",
                recovery_strategy="Use an admin token or request admin access.",
                details={"permitted_groups": groups},
            )

        group_guid = get_group_uuid_by_name(target_group)
        if group_guid is None:
            return error_response(
                error_code="GROUP_NOT_FOUND",
                message=f"Group not found: {target_group}",
                recovery_strategy="Ensure the group exists in the auth system.",
                details={"group_name": target_group},
            )

        try:
            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})
                    OPTIONAL MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)
                    OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)
                    RETURN c.guid AS client_guid, c.name AS client_name, p.guid AS portfolio_guid, w.guid AS watchlist_guid
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )

                node_guids = [record["client_guid"], record["portfolio_guid"], record["watchlist_guid"]]
                for guid in [g for g in node_guids if g]:
                    session.run(
                        """
                        MATCH (n {guid: $guid})-[r:IN_GROUP]->(:Group)
                        DELETE r
                        """,
                        guid=guid,
                    )
                    graph_index.create_relationship(
                        RelationType.IN_GROUP,
                        NodeLabel.CLIENT if guid == record["client_guid"] else (NodeLabel.PORTFOLIO if guid == record["portfolio_guid"] else NodeLabel.WATCHLIST),
                        guid,
                        NodeLabel.GROUP,
                        group_guid,
                    )

            return success_response(
                data={
                    "client_guid": record["client_guid"],
                    "client_name": record["client_name"],
                    "group_guid": group_guid,
                },
                message=f"Moved client '{record['client_name']}' to group {target_group}",
            )
        except Exception as e:
            return error_response(
                error_code="MOVE_GROUP_FAILED",
                message=f"Failed to move client group: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j connectivity.",
                details={"client_guid": client_guid, "target_group": target_group},
            )

    @mcp.tool(
        name="set_client_type",
        description="Set or change a client's type (admin only).",
    )
    def set_client_type(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to update",
        )],
        client_type: Annotated[str, Field(
            description="New client type (HEDGE_FUND, LONG_ONLY, etc.)",
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (admin required)",
        )] = None,
    ) -> ToolResponse:
        """Change the client type relationship."""
        is_admin, groups = _require_admin_group(auth_tokens)
        if not is_admin:
            return error_response(
                error_code="ACCESS_DENIED",
                message="Admin access required to change client type",
                recovery_strategy="Use an admin token or request admin access.",
                details={"permitted_groups": groups},
            )

        try:
            graph_index.create_client_type(
                code=client_type,
                name=client_type.replace("_", " ").title(),
            )
        except Exception:
            pass  # nosec B110

        try:
            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})
                    OPTIONAL MATCH (c)-[r:IS_TYPE_OF]->(:ClientType)
                    DELETE r
                    RETURN c.guid AS client_guid
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )

            graph_index.create_relationship(
                RelationType.IS_TYPE_OF,
                NodeLabel.CLIENT,
                client_guid,
                NodeLabel.CLIENT_TYPE,
                client_type,
            )

            return success_response(
                data={
                    "client_guid": client_guid,
                    "client_type": client_type,
                },
                message=f"Client type set to {client_type}",
            )
        except Exception as e:
            return error_response(
                error_code="SET_TYPE_FAILED",
                message=f"Failed to set client type: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j connectivity.",
                details={"client_guid": client_guid, "client_type": client_type},
            )

    @mcp.tool(
        name="repair_client",
        description=(
            "Repair missing client relationships and core nodes. ADMIN ONLY. "
            "Ensures IN_GROUP, HAS_PROFILE, HAS_PORTFOLIO, HAS_WATCHLIST, IS_TYPE_OF exist."
        ),
    )
    def repair_client(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to repair",
        )],
        group_name: Annotated[str | None, Field(
            default=None,
            description="Group name to use if client is missing IN_GROUP",
        )] = None,
        client_type: Annotated[str | None, Field(
            default=None,
            description="Client type to use if missing IS_TYPE_OF",
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (admin required)",
        )] = None,
    ) -> ToolResponse:
        """Repair missing client relationships and nodes."""
        import uuid

        is_admin, groups = _require_admin_group(auth_tokens)
        if not is_admin:
            return error_response(
                error_code="ACCESS_DENIED",
                message="Admin access required to repair clients",
                recovery_strategy="Use an admin token or request admin access.",
                details={"permitted_groups": groups},
            )

        try:
            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})
                    OPTIONAL MATCH (c)-[:IN_GROUP]->(g:Group)
                    OPTIONAL MATCH (c)-[:IS_TYPE_OF]->(ct:ClientType)
                    OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
                    OPTIONAL MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)
                    OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)
                    RETURN c.name AS name,
                           g.guid AS group_guid,
                           ct.code AS client_type,
                           cp.guid AS profile_guid,
                           p.guid AS portfolio_guid,
                           w.guid AS watchlist_guid
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )

            group_guid = record["group_guid"]
            if group_guid is None:
                if group_name is None:
                    return error_response(
                        error_code="GROUP_REQUIRED",
                        message="Client missing group; group_name is required to repair",
                        recovery_strategy="Provide group_name to repair IN_GROUP relationship.",
                        details={"client_guid": client_guid},
                    )
                group_guid = get_group_uuid_by_name(group_name)
                if group_guid is None:
                    return error_response(
                        error_code="GROUP_NOT_FOUND",
                        message=f"Group not found: {group_name}",
                        recovery_strategy="Ensure the group exists in the auth system.",
                        details={"group_name": group_name},
                    )
                graph_index.create_relationship(
                    RelationType.IN_GROUP,
                    NodeLabel.CLIENT,
                    client_guid,
                    NodeLabel.GROUP,
                    group_guid,
                )

            effective_type = record["client_type"] or client_type
            if effective_type is None:
                return error_response(
                    error_code="CLIENT_TYPE_REQUIRED",
                    message="Client missing type; client_type is required to repair",
                    recovery_strategy="Provide client_type to repair IS_TYPE_OF relationship.",
                    details={"client_guid": client_guid},
                )

            try:
                graph_index.create_client_type(
                    code=effective_type,
                    name=effective_type.replace("_", " ").title(),
                )
            except Exception:
                pass  # nosec B110

            if record["client_type"] is None:
                graph_index.create_relationship(
                    RelationType.IS_TYPE_OF,
                    NodeLabel.CLIENT,
                    client_guid,
                    NodeLabel.CLIENT_TYPE,
                    effective_type,
                )

            profile_guid = record["profile_guid"] or str(uuid.uuid4())
            if record["profile_guid"] is None:
                graph_index.create_client_profile(
                    guid=profile_guid,
                    client_guid=client_guid,
                    esg_constrained=False,
                )

            portfolio_guid = record["portfolio_guid"] or str(uuid.uuid4())
            if record["portfolio_guid"] is None:
                graph_index.create_portfolio(
                    guid=portfolio_guid,
                    client_guid=client_guid,
                    properties={"name": f"{record['name']} Portfolio" if record["name"] else "Portfolio"},
                )

            watchlist_guid = record["watchlist_guid"] or str(uuid.uuid4())
            if record["watchlist_guid"] is None:
                graph_index.create_watchlist(
                    guid=watchlist_guid,
                    client_guid=client_guid,
                    name=f"{record['name']} Watchlist" if record["name"] else "Watchlist",
                )

            for guid, label in [
                (portfolio_guid, NodeLabel.PORTFOLIO),
                (watchlist_guid, NodeLabel.WATCHLIST),
            ]:
                graph_index.create_relationship(
                    RelationType.IN_GROUP,
                    label,
                    guid,
                    NodeLabel.GROUP,
                    group_guid,
                )

            return success_response(
                data={
                    "client_guid": client_guid,
                    "group_guid": group_guid,
                    "client_type": effective_type,
                    "profile_guid": profile_guid,
                    "portfolio_guid": portfolio_guid,
                    "watchlist_guid": watchlist_guid,
                },
                message="Client repaired successfully",
            )
        except Exception as e:
            return error_response(
                error_code="REPAIR_FAILED",
                message=f"Failed to repair client: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j connectivity.",
                details={"client_guid": client_guid},
            )

    @mcp.tool(
        name="delete_client",
        description="Permanently delete a client and all related nodes (admin only).",
    )
    def delete_client(
        client_guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the client to delete",
        )],
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (admin required)",
        )] = None,
    ) -> ToolResponse:
        """Delete a client and related nodes."""
        is_admin, groups = _require_admin_group(auth_tokens)
        if not is_admin:
            return error_response(
                error_code="ACCESS_DENIED",
                message="Admin access required to delete clients",
                recovery_strategy="Use an admin token or request admin access.",
                details={"permitted_groups": groups},
            )

        try:
            with graph_index._get_session() as session:
                result = session.run(
                    """
                    MATCH (c:Client {guid: $client_guid})
                    OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)
                    OPTIONAL MATCH (c)-[:HAS_PORTFOLIO]->(p:Portfolio)
                    OPTIONAL MATCH (c)-[:HAS_WATCHLIST]->(w:Watchlist)
                    WITH c, c.guid AS guid, cp, p, w
                    DETACH DELETE cp, p, w, c
                    RETURN guid AS client_guid
                    """,
                    client_guid=client_guid,
                )
                record = result.single()
                if not record:
                    return error_response(
                        error_code="CLIENT_NOT_FOUND",
                        message=f"Client not found: {client_guid}",
                        recovery_strategy="Call list_clients to find valid client GUIDs.",
                        details={"client_guid": client_guid},
                    )

            return success_response(
                data={"client_guid": record["client_guid"]},
                message=f"Client deleted: {client_guid}",
            )
        except Exception as e:
            return error_response(
                error_code="CLIENT_DELETE_FAILED",
                message=f"Failed to delete client: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j connectivity.",
                details={"client_guid": client_guid},
            )
