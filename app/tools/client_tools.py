"""MCP Client Tools.

Provides client profile management and personalized news feeds.

Group Access Control:
    - Client creation requires authentication
    - Feeds are filtered to groups the user has access to
    - Portfolio/watchlist operations require client access
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

from app.services.graph_index import GraphIndex, NodeLabel, RelationType
from app.services.group_service import (
    resolve_permitted_groups,
    resolve_write_group,
)

if TYPE_CHECKING:
    pass

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def register_client_tools(mcp: FastMCP, graph_index: GraphIndex) -> None:
    """Register client tools with the MCP server."""

    @mcp.tool(
        name="create_client",
        description=(
            "Create an investment client profile for personalized news feeds. "
            "WORKFLOW: create_client → get_client_profile → add_to_portfolio/add_to_watchlist → get_client_feed. "
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
            benchmark: Benchmark ticker (e.g., 'SPY')
            horizon: short, medium, or long
            esg_constrained: Apply ESG filters

        Returns:
            client_guid, portfolio_guid, watchlist_guid, profile settings,
            group_guid: Group name/identifier (string like 'reuters-feed')
        """
        import uuid

        try:
            # Get write group from explicit tokens or context header
            group_guid = resolve_write_group(auth_tokens=auth_tokens)
            
            if group_guid is None:
                return error_response(
                    error_code="AUTH_REQUIRED",
                    message="Authentication required to create clients",
                    recovery_strategy="Pass auth_tokens parameter or include Authorization header with Bearer token.",
                )

            client_guid = str(uuid.uuid4())
            
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
                },
            )
            
            # Create profile
            profile_guid = str(uuid.uuid4())
            graph_index.create_client_profile(
                guid=profile_guid,
                client_guid=client_guid,
                mandate_type=mandate_type,
                benchmark_guid=benchmark,  # Will be None if not an actual GUID
                horizon=horizon,
                esg_constrained=esg_constrained,
            )
            
            # Create empty portfolio and watchlist
            portfolio_guid = str(uuid.uuid4())
            watchlist_guid = str(uuid.uuid4())
            
            graph_index.create_portfolio(
                guid=portfolio_guid,
                client_guid=client_guid,
                properties={"name": f"{name} Portfolio"},
            )
            
            graph_index.create_watchlist(
                guid=watchlist_guid,
                client_guid=client_guid,
                name=f"{name} Watchlist",
            )
            
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
                        "benchmark": benchmark,
                        "horizon": horizon,
                        "esg_constrained": esg_constrained,
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
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

            # Validate client exists
            client_node = graph_index.get_node(NodeLabel.CLIENT, client_guid)
            if not client_node:
                return error_response(
                    error_code="CLIENT_NOT_FOUND",
                    message=f"Client not found: {client_guid}",
                    recovery_strategy="Call list_clients to find valid client GUIDs, or create_client to create one.",
                    details={"client_guid": client_guid},
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
        name="add_to_portfolio",
        description=(
            "Add a stock position to a client's portfolio (actual holdings). "
            "WORKFLOW: create_client → add_to_portfolio (+ add_to_watchlist) → get_client_feed. "
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
            
            # Ensure instrument exists
            try:
                graph_index.create_instrument(
                    ticker=ticker.upper(),
                    name=ticker.upper(),
                    instrument_type="STOCK",
                    exchange="UNKNOWN",
                )
            except Exception:
                pass  # nosec B110 - May already exist
            
            # Add holding
            graph_index.add_holding(
                portfolio_guid=portfolio_guid,
                instrument_guid=f"{ticker.upper()}:UNKNOWN",
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
            "WORKFLOW: create_client → add_to_watchlist → get_watchlist_items → get_client_feed (includes watched stocks). "
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
            
            # Ensure instrument exists
            instrument_guid = f"{ticker.upper()}:UNKNOWN"
            try:
                graph_index.create_instrument(
                    ticker=ticker.upper(),
                    name=ticker.upper(),
                    instrument_type="STOCK",
                    exchange="UNKNOWN",
                )
            except Exception:
                pass  # nosec B110 - May already exist
            
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
            "FILTERS: Can filter by client_type (HEDGE_FUND, LONG_ONLY, etc.). "
            "RETURNS: Client GUIDs, names, types for further operations. "
            "NEXT STEPS: Use get_client_profile for full details on a specific client."
        ),
    )
    def list_clients(
        client_type: Annotated[str | None, Field(
            default=None,
            description="Filter: HEDGE_FUND|LONG_ONLY|QUANT|PENSION|FAMILY_OFFICE (omit for all)",
            examples=["HEDGE_FUND", "PENSION"],
        )] = None,
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
            limit: Max clients to return (default: 50)

        Returns:
            clients: List of {client_guid, name, client_type, group_guid, created_at}
            total_count: Number of clients returned
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

            # Build query with optional type filter
            type_filter = ""
            params: dict[str, Any] = {"limit": limit}
            
            if group_guids:
                params["group_guids"] = group_guids
                group_clause = "WHERE g.guid IN $group_guids"
            else:
                group_clause = ""  # No group filter for anonymous
                
            if client_type:
                type_filter = "AND ct.code = $client_type" if group_clause else "WHERE ct.code = $client_type"
                params["client_type"] = client_type.upper()

            with graph_index._get_session() as session:
                result = session.run(
                    f"""
                    MATCH (c:Client)-[:IN_GROUP]->(g:Group)
                    OPTIONAL MATCH (c)-[:IS_TYPE_OF]->(ct:ClientType)
                    {group_clause}
                    {type_filter}
                    RETURN c.guid AS client_guid, 
                           c.name AS name,
                           ct.code AS client_type,
                           g.guid AS group_guid,
                           c.created_at AS created_at
                    ORDER BY c.name
                    LIMIT $limit
                    """,
                    **params,
                )
                
                clients = []
                for record in result:
                    clients.append({
                        "client_guid": record["client_guid"],
                        "name": record["name"],
                        "client_type": record["client_type"],
                        "group_guid": record["group_guid"],
                        "created_at": record["created_at"],
                    })
            
            return success_response(
                data={
                    "clients": clients,
                    "total_count": len(clients),
                    "filters_applied": {
                        "client_type": client_type,
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
        name="get_client_profile",
        description=(
            "Get complete profile and settings for a specific client. "
            "WORKFLOW: create_client → get_client_profile → update_client_profile | add_to_portfolio/watchlist. "
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
            profile: mandate_type, benchmark, horizon, esg_constrained
            settings: alert_frequency, impact_threshold
            portfolio_guid, watchlist_guid, created_at
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

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
                           c.created_at AS created_at,
                           ct.code AS client_type,
                           g.guid AS group_guid,
                           cp.guid AS profile_guid,
                           cp.mandate_type AS mandate_type,
                           cp.horizon AS horizon,
                           cp.esg_constrained AS esg_constrained,
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
            
            return success_response(
                data={
                    "client_guid": record["client_guid"],
                    "name": record["name"],
                    "client_type": record["client_type"],
                    "group_guid": record["group_guid"],
                    "profile": {
                        "guid": record["profile_guid"],
                        "mandate_type": record["mandate_type"],
                        "benchmark": record["benchmark"],
                        "horizon": record["horizon"],
                        "esg_constrained": record["esg_constrained"],
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
            "WORKFLOW: create_client → add_to_portfolio → get_portfolio_holdings → remove_from_portfolio. "
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
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

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
                    ORDER BY h.weight DESC NULLS LAST
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
            "WORKFLOW: create_client → add_to_watchlist → get_watchlist_items → remove_from_watchlist. "
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
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

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
            "Update a client's profile settings (alert frequency, thresholds, investment style). "
            "WORKFLOW: create_client → get_client_profile → update_client_profile → get_client_feed. "
            "USE FOR: 'Change Citadel to daily alerts' or 'Set impact threshold to 70', 'Change mandate to equity_long_short'. "
            "USES OUTPUT FROM: create_client (client_guid) | get_client_profile (current settings). "
            "PROVIDES INPUT TO: get_client_feed (alert settings) | get_client_profile (returns updated). "
            "PARTIAL UPDATE: Only provide fields you want to change. Omitted fields keep current values. "
            "PREREQUISITE CHAIN: create_client → get_client_profile (see current) → update_client_profile (make changes). "
            "RETURNS: Updated profile with all current settings. "
            "ALERT FREQUENCY: realtime|hourly|daily|weekly. Affects notification frequency. "
            "IMPACT_THRESHOLD: 0-100. Higher = fewer alerts (only major news). 70+ for executives, 50 for analysts, 30 for researchers. "
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
            benchmark: Benchmark ticker
            horizon: short, medium, or long
            esg_constrained: Apply ESG filters

        Returns:
            Updated profile with all current settings
            changes: List of fields that were updated
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

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

            if not changes and benchmark is None:
                return error_response(
                    error_code="NO_UPDATES_PROVIDED",
                    message="No update fields provided",
                    recovery_strategy="Provide at least one field: alert_frequency, impact_threshold, mandate_type, horizon, benchmark, esg_constrained.",
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
                    # Ensure instrument exists
                    instrument_guid = f"{benchmark.upper()}:UNKNOWN"
                    try:
                        graph_index.create_instrument(
                            ticker=benchmark.upper(),
                            name=benchmark.upper(),
                            instrument_type="ETF",
                            exchange="UNKNOWN",
                        )
                    except Exception:
                        pass  # nosec B110 - May already exist
                    
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
            "WORKFLOW: add_to_portfolio → get_portfolio_holdings → remove_from_portfolio (confirm with next get_portfolio_holdings). "
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
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

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
            "WORKFLOW: add_to_watchlist → get_watchlist_items → remove_from_watchlist (confirm with next get_watchlist_items). "
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
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

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
