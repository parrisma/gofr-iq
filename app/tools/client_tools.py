"""MCP Client Tools.

Provides client profile management and personalized news feeds.
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
    """Register client tools with the MCP server."""

    @mcp.tool(
        name="create_client",
        description=(
            "Create a client profile for personalized news. "
            "Use when setting up a new user who needs tailored news feeds "
            "based on their portfolio and interests."
        ),
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
            name: Client name (e.g., "Citadel", "BlackRock")
            group_guid: Group for permissions
            client_type: HEDGE_FUND, LONG_ONLY, QUANT, PENSION, or FAMILY_OFFICE
            alert_frequency: realtime, hourly, daily, or weekly
            impact_threshold: Min impact score 0-100 for alerts (default: 50)
            mandate_type: Investment style (e.g., "equity_long_short")
            benchmark: Benchmark ticker (e.g., "SPY")
            horizon: short, medium, or long
            esg_constrained: Apply ESG filters

        Returns:
            client_guid, portfolio_guid, watchlist_guid, profile settings
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
        description=(
            "Get a personalized news feed for a client. "
            "Shows relevant news based on their portfolio holdings and watchlist. "
            "Results ranked by impact and relevance to client's positions."
        ),
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

        Args:
            client_guid: Client to get feed for
            group_guids: Groups client can access
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
        description=(
            "Add a stock holding to a client's portfolio. "
            "News about portfolio holdings gets higher priority in the client's feed."
        ),
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
            client_guid: Client to update
            ticker: Stock symbol (e.g., "AAPL", "9988.HK")
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
            "Add a stock to a client's watchlist. "
            "Use to track stocks the client is interested in but doesn't hold."
        ),
    )
    def add_to_watchlist(
        client_guid: str,
        ticker: str,
        alert_threshold: float | None = None,
    ) -> ToolResponse:
        """Add an instrument to client's watchlist.

        Args:
            client_guid: Client to update
            ticker: Stock symbol (e.g., "TSLA", "700.HK")
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
