"""MCP Client Tools - Phase 4.

Provides MCP tools for client profile management and personalized news feeds.

Tools:
- create_client: Create a new client with optional portfolio and watchlist
- get_client_feed: Get personalized news feed for a client
- add_to_portfolio: Add a holding to client's portfolio
- add_to_watchlist: Add an instrument to client's watchlist
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

from app.services.graph_index import GraphIndex, NodeLabel, RelationType

if TYPE_CHECKING:
    pass

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def register_client_tools(mcp: FastMCP, graph_index: GraphIndex) -> None:
    """Register client tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        graph_index: GraphIndex for client/portfolio management
    """

    @mcp.tool(
        name="create_client",
        description="Create a new client profile for personalized news feeds. "
        "Clients can have portfolios (holdings) and watchlists (instruments of interest).",
    )
    def create_client(
        name: str,
        group_guid: str,
        client_type: str = "HEDGE_FUND",
        alert_frequency: str = "realtime",
        impact_threshold: float = 50.0,
        mandate_type: str | None = None,
        benchmark: str | None = None,
        horizon: str | None = None,
        esg_constrained: bool = False,
    ) -> ToolResponse:
        """Create a new client profile.

        Args:
            name: Client name (e.g., "Citadel", "BlackRock Global Allocation")
            group_guid: Group GUID this client belongs to (for permissions)
            client_type: Type of client. Options:
                - HEDGE_FUND: Active trading, high alert frequency (default)
                - LONG_ONLY: Buy-and-hold, fundamental focus
                - QUANT: Systematic/algorithmic, data-driven
                - PENSION: Long-term, lower turnover
                - FAMILY_OFFICE: Multi-asset, balanced approach
            alert_frequency: How often to receive alerts:
                - realtime: Immediate alerts (default for hedge funds)
                - hourly: Hourly digest
                - daily: Daily digest
                - weekly: Weekly summary
            impact_threshold: Minimum impact score (0-100) to include in feed.
                Lower = more news, Higher = only major events. Default: 50.0
            mandate_type: Investment mandate (e.g., "equity_long_short", "global_macro")
            benchmark: Benchmark index (e.g., "SPY", "QQQ")
            horizon: Investment horizon (e.g., "short", "medium", "long")
            esg_constrained: Whether ESG constraints apply

        Returns:
            JSON response with created client details including:
            - client_guid: Unique identifier for the client
            - name: Client name
            - client_type: Client type code
            - group_guid: Associated group
            - profile: Client profile settings

        Errors:
            - CLIENT_EXISTS: A client with this name already exists in the group
            - INVALID_CLIENT_TYPE: Unknown client type
            - CREATE_ERROR: General creation failure
        """
        import uuid

        try:
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
        description="Get a personalized news feed for a client based on their portfolio, "
        "watchlist, and preferences. Returns ranked articles with relevance scores.",
    )
    def get_client_feed(
        client_guid: str,
        group_guids: list[str],
        limit: int = 20,
        min_impact_score: float | None = None,
        impact_tiers: list[str] | None = None,
        include_portfolio: bool = True,
        include_watchlist: bool = True,
    ) -> ToolResponse:
        """Get personalized news feed for a client.

        The feed is ranked by:
        1. Impact score of the news
        2. Relevance to portfolio holdings (weighted by position size)
        3. Relevance to watchlist instruments
        4. Time decay (recent news ranked higher)

        Args:
            client_guid: The client GUID to get feed for
            group_guids: List of group GUIDs the client can access (for permissions)
            limit: Maximum number of articles to return (default: 20)
            min_impact_score: Only include news with impact >= this score (0-100)
            impact_tiers: Filter by impact tiers. Options:
                - PLATINUM: Market-moving events (>5% stock moves)
                - GOLD: High impact events (3-5% moves)
                - SILVER: Notable events (1-3% moves)
                - BRONZE: Moderate events (0.5-1% moves)
                - STANDARD: Routine news (<0.5% moves)
            include_portfolio: Include news affecting portfolio holdings (default: True)
            include_watchlist: Include news affecting watchlist instruments (default: True)

        Returns:
            JSON response with ranked news feed:
            - articles: List of articles with:
                - document_guid: Document identifier
                - title: Article title
                - impact_score: Impact score (0-100)
                - impact_tier: Impact classification
                - relevance_score: Personalized relevance score
                - affected_instruments: List of tickers mentioned
                - created_at: Publication timestamp
            - total_count: Number of articles returned
            - filters_applied: Summary of filters used

        Errors:
            - CLIENT_NOT_FOUND: The client_guid doesn't exist
            - NO_PERMISSIONS: Client doesn't have access to any of the specified groups
            - FEED_ERROR: General feed retrieval failure
        """
        try:
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
                recovery_strategy="Check the client_guid and group_guids are valid.",
            )

    @mcp.tool(
        name="add_to_portfolio",
        description="Add a stock holding to a client's portfolio. "
        "News affecting portfolio holdings will be prioritized in the client's feed.",
    )
    def add_to_portfolio(
        client_guid: str,
        ticker: str,
        weight: float,
        shares: int | None = None,
        avg_cost: float | None = None,
    ) -> ToolResponse:
        """Add a holding to client's portfolio.

        Args:
            client_guid: The client GUID
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT")
            weight: Portfolio weight as decimal (e.g., 0.10 for 10%)
            shares: Number of shares held (optional)
            avg_cost: Average cost basis per share (optional)

        Returns:
            JSON response with:
            - ticker: The ticker added
            - weight: Portfolio weight
            - message: Confirmation message

        Errors:
            - CLIENT_NOT_FOUND: The client doesn't exist
            - PORTFOLIO_NOT_FOUND: Client doesn't have a portfolio
            - ADD_ERROR: General failure
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
        description="Add an instrument to a client's watchlist. "
        "News affecting watchlist instruments will be included in the client's feed.",
    )
    def add_to_watchlist(
        client_guid: str,
        ticker: str,
        alert_threshold: float | None = None,
    ) -> ToolResponse:
        """Add an instrument to client's watchlist.

        Args:
            client_guid: The client GUID
            ticker: Stock ticker symbol (e.g., "AAPL", "TSLA")
            alert_threshold: Optional minimum impact score for alerts on this ticker

        Returns:
            JSON response with:
            - ticker: The ticker added
            - alert_threshold: Alert threshold if set
            - message: Confirmation message

        Errors:
            - CLIENT_NOT_FOUND: The client doesn't exist
            - WATCHLIST_NOT_FOUND: Client doesn't have a watchlist
            - ADD_ERROR: General failure
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
