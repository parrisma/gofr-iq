"""MCP Graph Tools.

Provides knowledge graph exploration and market context.

Group Access Control:
    - Document queries are filtered to groups the user has access to
    - Anonymous users only see documents in the public group
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

from app.services.graph_index import GraphIndex, NodeLabel, RelationType
from app.services.group_service import resolve_permitted_groups

if TYPE_CHECKING:
    pass

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def register_graph_tools(mcp: FastMCP, graph_index: GraphIndex) -> None:
    """Register graph exploration tools with the MCP server."""

    @mcp.tool(
        name="explore_graph",
        description=(
            "Explore knowledge graph relationships from any starting point. "
            "WORKFLOW: query_documents (find entities) → explore_graph (relationships) → get_instrument_news (details). "
            "USE FOR: 'What affects AAPL?', 'TSLA peers?', 'Companies in Energy sector?', 'Who holds this stock?' "
            "USES OUTPUT FROM: query_documents (entities found) | get_instrument_news (ticker context). "
            "PROVIDES INPUT TO: get_instrument_news (for detail drill-down) | get_market_context (for context). "
            "NODE_TYPES: INSTRUMENT (ticker), COMPANY, DOCUMENT (guid), EVENT_TYPE, SECTOR, CLIENT. "
            "RELATIONSHIPS: AFFECTS|PEER_OF|MENTIONS|HOLDS|WATCHES|ISSUED_BY|BELONGS_TO. "
            "TIP: Start with node_type=INSTRUMENT, node_id=ticker (e.g., 'AAPL'). Increase max_depth to see deeper connections (slower)."
        ),
    )
    def explore_graph(
        node_type: Annotated[str, Field(
            description="Type of node to start from: INSTRUMENT (ticker), COMPANY, DOCUMENT (guid), EVENT_TYPE, SECTOR, CLIENT",
            examples=["INSTRUMENT", "COMPANY", "DOCUMENT", "SECTOR"],
        )],
        node_id: Annotated[str, Field(
            min_length=1,
            description="Identifier of the starting node (ticker like 'AAPL', GUID, or name)",
            examples=["AAPL", "TSLA", "Technology"],
        )],
        relationship_types: Annotated[list[str] | None, Field(
            default=None,
            description="Filter: AFFECTS|PEER_OF|MENTIONS|HOLDS|WATCHES|ISSUED_BY|BELONGS_TO",
            examples=[["AFFECTS", "PEER_OF"]],
        )] = None,
        max_depth: Annotated[int, Field(
            default=1,
            ge=1,
            le=3,
            description="Hops: 1=direct neighbors, 2=neighbors-of-neighbors, 3=max (slower)",
        )] = 1,
        limit: Annotated[int, Field(
            default=20,
            ge=1,
            le=100,
            description="Max related nodes to return (default: 20)",
        )] = 20,
    ) -> ToolResponse:
        """Traverse relationships from a starting node.

        Args:
            node_type: INSTRUMENT (ticker), COMPANY, DOCUMENT (guid), EVENT_TYPE, SECTOR, CLIENT
            node_id: Identifier (ticker like 'AAPL', or GUID, or name)
            relationship_types: Filter traversal - AFFECTS, PEER_OF, MENTIONS, HOLDS, WATCHES, etc.
            max_depth: How far to traverse (1-3, default: 1)
            limit: Max related nodes to return (default: 20)

        Returns:
            start_node: Starting point info
            relationships: Connected nodes with type, properties, confidence
            total_found: Number of relationships discovered
        """
        try:
            # Validate node type
            try:
                node_label = NodeLabel[node_type.upper()]
            except KeyError:
                return error_response(
                    error_code="INVALID_NODE_TYPE",
                    message=f"Invalid node type: {node_type}",
                    recovery_strategy="Valid types: INSTRUMENT|COMPANY|DOCUMENT|EVENT_TYPE|SECTOR|CLIENT",
                    details={"provided": node_type, "valid": [label.name for label in NodeLabel]},
                )

            # Validate relationship types if provided
            if relationship_types:
                try:
                    rel_types = [RelationType[rt.upper()] for rt in relationship_types]
                except KeyError as e:
                    return error_response(
                        error_code="INVALID_RELATIONSHIP_TYPE",
                        message=f"Invalid relationship type: {e}",
                        recovery_strategy="Valid types: AFFECTS|PEER_OF|MENTIONS|HOLDS|WATCHES|ISSUED_BY|BELONGS_TO",
                        details={"valid": [rel.name for rel in RelationType]},
                    )
            else:
                rel_types = None

            # Get the starting node
            if node_type.upper() == "INSTRUMENT":
                # For instruments, use ticker as ID
                start_node = graph_index.get_instrument(node_id.upper())
                if not start_node:
                    return error_response(
                        error_code="INSTRUMENT_NOT_FOUND",
                        message=f"Instrument not found: {node_id}",
                        recovery_strategy="Verify ticker symbol. Try get_market_context with correct ticker.",
                        details={"ticker": node_id.upper()},
                    )
                node_guid = f"{node_id.upper()}:NYSE"  # Default exchange
            else:
                start_node = graph_index.get_node(node_label, node_id)
                if not start_node:
                    return error_response(
                        error_code="NODE_NOT_FOUND",
                        message=f"{node_type} not found: {node_id}",
                        recovery_strategy="Verify the node ID. For instruments, use get_market_context first.",
                        details={"node_type": node_type, "node_id": node_id},
                    )
                node_guid = node_id

            # Build Cypher query for traversal
            with graph_index._get_session() as session:
                if rel_types:
                    rel_pattern = "|".join([f":{rt.value}" for rt in rel_types])
                    query = (
                        "MATCH (start:" + node_label.value + " {guid: $node_guid})\n"
                        "MATCH path = (start)-[r:" + rel_pattern + "*1.." + str(max_depth) + "]-(related)\n"
                        "RETURN DISTINCT \n"
                        "    type(relationships(path)[0]) as rel_type,\n"
                        "    related,\n"
                        "    labels(related)[0] as related_label,\n"
                        "    properties(relationships(path)[0]) as rel_props\n"
                        "LIMIT $limit"
                    )
                else:
                    query = (
                        "MATCH (start:" + node_label.value + " {guid: $node_guid})\n"
                        "MATCH path = (start)-[r*1.." + str(max_depth) + "]-(related)\n"
                        "RETURN DISTINCT \n"
                        "    type(relationships(path)[0]) as rel_type,\n"
                        "    related,\n"
                        "    labels(related)[0] as related_label,\n"
                        "    properties(relationships(path)[0]) as rel_props\n"
                        "LIMIT $limit"
                    )

                result = session.run(query, node_guid=node_guid, limit=limit)  # type: ignore[arg-type]

                relationships = []
                for record in result:
                    rel_data = {
                        "relationship_type": record["rel_type"],
                        "target_node": {
                            "label": record["related_label"],
                            "guid": record["related"].get("guid"),
                            "name": record["related"].get("name") or record["related"].get("title"),
                            "properties": dict(record["related"]),
                        },
                        "properties": dict(record["rel_props"]) if record["rel_props"] else {},
                    }
                    relationships.append(rel_data)

            return success_response(
                data={
                    "start_node": {
                        "label": node_label.value,
                        "guid": start_node.guid,
                        "properties": start_node.properties,
                    },
                    "relationships": relationships,
                    "total_found": len(relationships),
                    "depth": max_depth,
                },
                message=f"Found {len(relationships)} related nodes",
            )

        except Exception as e:
            return error_response(
                error_code="GRAPH_EXPLORATION_FAILED",
                message=f"Graph exploration failed: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j (bolt://localhost:7687). Check node_type and node_id.",
                details={"node_type": node_type, "node_id": node_id},
            )

    @mcp.tool(
        name="get_market_context",
        description=(
            "Get comprehensive market background on a stock ticker. "
            "WORKFLOW: Often used after query_documents finds a ticker | provides context before explore_graph. "
            "USE FOR: 'Tell me about AAPL', 'TSLA context', 'What indices is NVDA in?', 'Who are TSLA peers?' "
            "USES OUTPUT FROM: query_documents (ticker identified) | explore_graph (to fill context). "
            "PROVIDES INPUT TO: explore_graph (for deeper relationship queries) | get_instrument_news (complementary details). "
            "RETURNS: Company info, peer companies, recent events, index memberships, sector. "
            "INCLUDES: Company fundamentals, peer correlation, recent news (30 days default), S&P 500/other indices, sector. "
            "RECOMMENDED FLOW: Start here after query_documents finds a ticker, then use explore_graph for deeper relationships."
        ),
    )
    def get_market_context(
        ticker: Annotated[str, Field(
            min_length=1,
            max_length=20,
            description="Stock ticker symbol (e.g., 'AAPL', '700.HK', 'BABA')",
            examples=["AAPL", "TSLA", "700.HK", "9988.HK"],
        )],
        include_peers: Annotated[bool, Field(
            default=True,
            description="Include similar/peer companies (default: True)",
        )] = True,
        include_events: Annotated[bool, Field(
            default=True,
            description="Include recent news/events affecting this stock (default: True)",
        )] = True,
        include_indices: Annotated[bool, Field(
            default=True,
            description="Include index memberships like S&P 500 (default: True)",
        )] = True,
        days_back: Annotated[int, Field(
            default=30,
            ge=1,
            le=365,
            description="How many days of event history (default: 30)",
        )] = 30,
    ) -> ToolResponse:
        """Get market context for an instrument.

        Args:
            ticker: Stock symbol (e.g., 'AAPL', '700.HK')
            include_peers: Include similar companies (default: True)
            include_events: Include recent news/events (default: True)
            include_indices: Include index memberships (default: True)
            days_back: How many days of history (default: 30)

        Returns:
            instrument: Basic info (ticker, name, exchange)
            company: Issuer details
            peers: Similar companies with correlation
            recent_events: Recent news affecting this stock
            indices: Index memberships (S&P 500, etc.)
            sector: Industry classification
        """
        try:
            # Get the instrument
            instrument = graph_index.get_instrument(ticker.upper())
            if not instrument:
                return error_response(
                    error_code="INSTRUMENT_NOT_FOUND",
                    message=f"Instrument not found: {ticker}",
                    recovery_strategy="Verify ticker symbol format (e.g., AAPL, 9988.HK). Ticker may not exist in graph.",
                    details={"ticker": ticker.upper()},
                )

            context: dict[str, Any] = {
                "instrument": {
                    "ticker": instrument.properties.get("ticker"),
                    "name": instrument.properties.get("name"),
                    "type": instrument.properties.get("instrument_type"),
                    "exchange": instrument.properties.get("exchange"),
                    "currency": instrument.properties.get("currency"),
                    "country": instrument.properties.get("country"),
                },
            }

            with graph_index._get_session() as session:
                instrument_guid = instrument.guid

                # Get issuing company
                result = session.run(
                    """
                    MATCH (i:Instrument {guid: $guid})-[:ISSUED_BY]->(c:Company)
                    RETURN c
                    """,
                    guid=instrument_guid,
                )
                record = result.single()
                if record:
                    context["company"] = dict(record["c"])

                # Get peers if requested
                if include_peers:
                    result = session.run(
                        """
                        MATCH (i:Instrument {guid: $guid})-[:ISSUED_BY]->(c:Company)
                        MATCH (c)-[r:PEER_OF]-(peer:Company)
                        RETURN peer, r.correlation as correlation
                        LIMIT 10
                        """,
                        guid=instrument_guid,
                    )
                    peers = []
                    for record in result:
                        peers.append({
                            "company": dict(record["peer"]),
                            "correlation": record.get("correlation"),
                        })
                    context["peers"] = peers

                # Get recent events if requested
                if include_events:
                    result = session.run(
                        """
                        MATCH (d:Document)-[a:AFFECTS]->(i:Instrument {guid: $guid})
                        WHERE d.created_at > datetime() - duration({days: $days_back})
                        OPTIONAL MATCH (d)-[:TRIGGERED_BY]->(et:EventType)
                        RETURN d, et, a.magnitude as magnitude, a.direction as direction
                        ORDER BY d.created_at DESC
                        LIMIT 20
                        """,
                        guid=instrument_guid,
                        days_back=days_back,
                    )
                    events = []
                    for record in result:
                        event_data = {
                            "document": {
                                "guid": record["d"]["guid"],
                                "title": record["d"].get("title"),
                                "created_at": str(record["d"].get("created_at")),
                                "impact_score": record["d"].get("impact_score"),
                                "impact_tier": record["d"].get("impact_tier"),
                            },
                            "magnitude": record.get("magnitude"),
                            "direction": record.get("direction"),
                        }
                        if record["et"]:
                            event_data["event_type"] = {
                                "code": record["et"]["code"],
                                "name": record["et"].get("name"),
                            }
                        events.append(event_data)
                    context["recent_events"] = events

                # Get index memberships if requested
                if include_indices:
                    result = session.run(
                        """
                        MATCH (i:Instrument {guid: $guid})-[c:CONSTITUENT_OF]->(idx:Index)
                        RETURN idx, c.weight as weight
                        """,
                        guid=instrument_guid,
                    )
                    indices = []
                    for record in result:
                        indices.append({
                            "index": dict(record["idx"]),
                            "weight": record.get("weight"),
                        })
                    context["indices"] = indices

                # Get sector
                result = session.run(
                    """
                    MATCH (i:Instrument {guid: $guid})-[:ISSUED_BY]->(c:Company)-[:BELONGS_TO]->(s:Sector)
                    RETURN s
                    """,
                    guid=instrument_guid,
                )
                record = result.single()
                if record:
                    context["sector"] = dict(record["s"])

            return success_response(
                data=context,
                message=f"Market context for {ticker.upper()}",
            )

        except Exception as e:
            return error_response(
                error_code="MARKET_CONTEXT_FAILED",
                message=f"Failed to get market context: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Check ticker format (e.g., AAPL, 700.HK).",
                details={"ticker": ticker},
            )

    @mcp.tool(
        name="get_instrument_news",
        description=(
            "Get news articles and events affecting a specific stock. "
            "WORKFLOW: query_documents (find companies) → get_instrument_news (ticker drill-down) | explore_graph (relationships). "
            "USE FOR: 'Why is AAPL moving?', 'TSLA news', 'What's happening with NVDA?', 'Recent events for ticker X' "
            "USES OUTPUT FROM: query_documents (ticker identified) | explore_graph (ticker context). "
            "PROVIDES INPUT TO: explore_graph (for relationship drilling) | get_market_context (complementary view). "
            "SORTED BY: Impact score (highest first), then recency. "
            "RETURNS: Articles with impact_score, event_type, direction (positive/negative), publication date. "
            "DIFFERENT FROM query_documents: This is ticker-specific news (stock drill-down); query_documents is broad topic search. "
            "FILTER: Impact tier, time window, event type (earnings, M&A, regulatory, etc.)"
        ),
    )
    def get_instrument_news(
        ticker: Annotated[str, Field(
            min_length=1,
            max_length=20,
            description="Stock ticker symbol (e.g., 'AAPL', 'BABA', '700.HK')",
            examples=["AAPL", "TSLA", "BABA"],
        )],
        days_back: Annotated[int, Field(
            default=7,
            ge=1,
            le=365,
            description="How many days back to search (default: 7)",
        )] = 7,
        min_impact_score: Annotated[float | None, Field(
            default=None,
            ge=0.0,
            le=100.0,
            description="Minimum importance score 0-100 to filter articles",
        )] = None,
        limit: Annotated[int, Field(
            default=20,
            ge=1,
            le=100,
            description="Max articles to return (default: 20)",
        )] = 20,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Get news affecting a stock.

        Results are automatically limited to groups you have permission to access.
        Groups are string identifiers like 'reuters-feed' or 'public', not UUIDs.
        Anonymous users only see news from the public group.

        Args:
            ticker: Stock symbol (e.g., 'AAPL', 'BABA')
            days_back: How many days back (default: 7)
            min_impact_score: Min importance 0-100
            limit: Max articles (default: 20)

        Returns:
            articles: News with title, impact_score, event_type, direction (positive/negative)
            total_found: Number of matching articles
        """
        try:
            # Get permitted groups from explicit tokens or context header
            group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

            # Verify instrument exists
            instrument = graph_index.get_instrument(ticker.upper())
            if not instrument:
                return error_response(
                    error_code="INSTRUMENT_NOT_FOUND",
                    message=f"Instrument not found: {ticker}",
                    recovery_strategy="Verify ticker symbol. Use get_market_context to check if ticker exists.",
                    details={"ticker": ticker.upper()},
                )

            with graph_index._get_session() as session:
                # Build query with filters
                where_clauses = ["d.created_at > datetime() - duration({days: $days_back})"]
                if min_impact_score is not None:
                    where_clauses.append("d.impact_score >= $min_impact_score")

                where_clause = " AND ".join(where_clauses)

                query = f"""
                MATCH (d:Document)-[:IN_GROUP]->(g:Group)
                WHERE g.guid IN $group_guids
                MATCH (d)-[a:AFFECTS]->(i:Instrument {{guid: $instrument_guid}})
                WHERE {where_clause}
                OPTIONAL MATCH (d)-[:TRIGGERED_BY]->(et:EventType)
                RETURN d, et, a.magnitude as magnitude, a.direction as direction
                ORDER BY d.impact_score DESC, d.created_at DESC
                LIMIT $limit
                """

                result = session.run(
                    query,  # type: ignore[arg-type]
                    group_guids=group_guids,
                    instrument_guid=instrument.guid,
                    days_back=days_back,
                    min_impact_score=min_impact_score,
                    limit=limit,
                )

                articles = []
                for record in result:
                    article = {
                        "document_guid": record["d"]["guid"],
                        "title": record["d"].get("title"),
                        "impact_score": record["d"].get("impact_score"),
                        "impact_tier": record["d"].get("impact_tier"),
                        "magnitude": record.get("magnitude"),
                        "direction": record.get("direction"),
                        "created_at": str(record["d"].get("created_at")),
                    }
                    if record["et"]:
                        article["event_type"] = {
                            "code": record["et"]["code"],
                            "name": record["et"].get("name"),
                        }
                    articles.append(article)

            return success_response(
                data={
                    "ticker": ticker.upper(),
                    "articles": articles,
                    "total_found": len(articles),
                },
                message=f"Found {len(articles)} articles for {ticker.upper()}",
            )

        except Exception as e:
            return error_response(
                error_code="INSTRUMENT_NEWS_FAILED",
                message=f"Failed to get instrument news: {e!s}",
                recovery_strategy="Run health_check to verify Neo4j. Check ticker and filters.",
                details={"ticker": ticker, "days_back": days_back},
            )
