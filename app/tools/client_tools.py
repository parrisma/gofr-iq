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
            "USE FOR: Setting up hedge funds, asset managers, family offices, etc. "
            "REQUIRES AUTH: Must have a valid token. "
            "CREATES: Client + empty portfolio + empty watchlist. "
            "NEXT STEPS: Use add_to_portfolio/add_to_watchlist to populate holdings."
        ),
    )
    def create_client(
        name: Annotated[str, Field(
            min_length=1,
            max_length=255,
            description="Client name (e.g., 'Citadel', 'BlackRock')",
        )],
        client_type: Annotated[str, Field(
            default="HEDGE_FUND",
            description="Client type: HEDGE_FUND, LONG_ONLY, QUANT, PENSION, or FAMILY_OFFICE",
        )] = "HEDGE_FUND",
        alert_frequency: Annotated[str, Field(
            default="realtime",
            description="Alert frequency: realtime, hourly, daily, or weekly",
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
        )] = None,
        benchmark: Annotated[str | None, Field(
            default=None,
            description="Benchmark ticker symbol (e.g., 'SPY', 'QQQ')",
        )] = None,
        horizon: Annotated[str | None, Field(
            default=None,
            description="Investment horizon: short, medium, or long",
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
                    recovery_strategy="Provide a valid Bearer token in the Authorization header.",
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
                error_code="CREATE_ERROR",
                message=f"Failed to create client: {e!s}",
                recovery_strategy="Check the input parameters and try again.",
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
                    recovery_strategy="Verify the client_guid is correct. Use create_client to create a new client.",
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
                error_code="FEED_ERROR",
                message=f"Failed to retrieve feed: {e!s}",
                recovery_strategy="Check the client_guid is valid.",
            )

    @mcp.tool(
        name="add_to_portfolio",
        description=(
            "Add a stock position to a client's portfolio. "
            "USE FOR: Recording actual holdings (not just interest). "
            "EFFECT: News about holdings gets HIGHER priority in get_client_feed. "
            "PREREQUISITE: Client must exist. Creates instrument if needed. "
            "TIP: weight is decimal (0.10 = 10%), not percentage."
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
                        recovery_strategy="Create a portfolio for the client first.",
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
                error_code="ADD_ERROR",
                message=f"Failed to add to portfolio: {e!s}",
                recovery_strategy="Verify the client_guid and ticker are valid.",
            )

    @mcp.tool(
        name="add_to_watchlist",
        description=(
            "Add a stock to a client's watchlist for monitoring (not holdings). "
            "USE FOR: Tracking stocks of interest without actual positions. "
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
                        recovery_strategy="Create a watchlist for the client first.",
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
                error_code="ADD_ERROR",
                message=f"Failed to add to watchlist: {e!s}",
                recovery_strategy="Verify the client_guid and ticker are valid.",
            )
