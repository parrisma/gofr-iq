"""MCP Graph Tools - Phase 5.

Provides MCP tools for graph exploration and market context.

Tools:
- explore_graph: Traverse from a node to discover related entities
- get_market_context: Get market context for an instrument (events, peers)
- get_instrument_news: Get news affecting a specific instrument
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


def register_graph_tools(mcp: FastMCP, graph_index: GraphIndex) -> None:
    """Register graph exploration tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        graph_index: GraphIndex for graph queries
    """

    @mcp.tool(
        name="explore_graph",
        description="Traverse the knowledge graph from a starting node to discover related entities. "
        "Use this to answer questions like 'What else affects AAPL?' or 'What companies are peers of TSLA?'",
    )
    def explore_graph(
        node_type: str,
        node_id: str,
        relationship_types: list[str] | None = None,
        max_depth: int = 1,
        limit: int = 20,
    ) -> ToolResponse:
        """Explore relationships from a node in the graph.

        Args:
            node_type: Type of the starting node. Options:
                - INSTRUMENT: Stock, ETF, etc. (use ticker as node_id, e.g., "AAPL")
                - COMPANY: Company entity (use ticker/name as node_id)
                - DOCUMENT: News document (use GUID as node_id)
                - EVENT_TYPE: Event category (use code as node_id, e.g., "EARNINGS_BEAT")
                - SECTOR: Industry sector (use name as node_id)
                - CLIENT: Client profile (use GUID as node_id)
            node_id: Identifier for the node (ticker, GUID, or name depending on type)
            relationship_types: Optional list of relationship types to traverse. Options:
                - AFFECTS: Documents affecting instruments
                - TRIGGERED_BY: Documents triggering events
                - MENTIONS: Documents mentioning companies
                - PEER_OF: Peer companies
                - CONSTITUENT_OF: Index constituents
                - ISSUED_BY: Instrument issuer
                - HOLDS: Portfolio holdings
                - WATCHES: Watchlist instruments
                If not specified, all relationships are traversed.
            max_depth: Maximum traversal depth (1-3, default: 1)
            limit: Maximum number of related nodes to return (default: 20)

        Returns:
            JSON response with:
            - start_node: Starting node information
            - relationships: List of discovered relationships with:
                - relationship_type: Type of relationship
                - target_node: Related node information
                - properties: Relationship properties (weight, confidence, etc.)
            - total_found: Total relationships discovered
            - depth: Actual traversal depth

        Errors:
            - NODE_NOT_FOUND: Starting node doesn't exist
            - INVALID_NODE_TYPE: Unknown node type
            - INVALID_RELATIONSHIP: Unknown relationship type
            - GRAPH_ERROR: Graph query failed
        """
        try:
            # Validate node type
            try:
                node_label = NodeLabel[node_type.upper()]
            except KeyError:
                return error_response(
                    error_code="INVALID_NODE_TYPE",
                    message=f"Invalid node type: {node_type}",
                    recovery_strategy=f"Valid types: {', '.join([label.name for label in NodeLabel])}",
                )

            # Validate relationship types if provided
            if relationship_types:
                try:
                    rel_types = [RelationType[rt.upper()] for rt in relationship_types]
                except KeyError as e:
                    return error_response(
                        error_code="INVALID_RELATIONSHIP",
                        message=f"Invalid relationship type: {e}",
                        recovery_strategy=f"Valid types: {', '.join([rel.name for rel in RelationType])}",
                    )
            else:
                rel_types = None

            # Get the starting node
            if node_type.upper() == "INSTRUMENT":
                # For instruments, use ticker as ID
                start_node = graph_index.get_instrument(node_id.upper())
                if not start_node:
                    return error_response(
                        error_code="NODE_NOT_FOUND",
                        message=f"Instrument not found: {node_id}",
                        recovery_strategy="Check the ticker symbol and try again.",
                    )
                node_guid = f"{node_id.upper()}:NYSE"  # Default exchange
            else:
                start_node = graph_index.get_node(node_label, node_id)
                if not start_node:
                    return error_response(
                        error_code="NODE_NOT_FOUND",
                        message=f"{node_type} not found: {node_id}",
                        recovery_strategy="Check the node ID and try again.",
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
                error_code="GRAPH_ERROR",
                message=f"Graph exploration failed: {e!s}",
                recovery_strategy="Check the node type and ID, then try again.",
            )

    @mcp.tool(
        name="get_market_context",
        description="Get comprehensive market context for an instrument including "
        "recent events, peer companies, index memberships, and related factors.",
    )
    def get_market_context(
        ticker: str,
        include_peers: bool = True,
        include_events: bool = True,
        include_indices: bool = True,
        days_back: int = 30,
    ) -> ToolResponse:
        """Get market context for an instrument.

        Args:
            ticker: Instrument ticker symbol (e.g., "AAPL", "TSLA")
            include_peers: Include peer companies (default: True)
            include_events: Include recent events affecting this instrument (default: True)
            include_indices: Include index memberships (default: True)
            days_back: Look back period for events in days (default: 30)

        Returns:
            JSON response with:
            - instrument: Instrument details (ticker, name, type, exchange)
            - company: Issuing company information
            - peers: List of peer companies with correlation
            - recent_events: Recent documents/events affecting this instrument
            - indices: Index memberships
            - sector: Sector classification
            - statistics: Key statistics (if available)

        Errors:
            - INSTRUMENT_NOT_FOUND: Instrument doesn't exist
            - MARKET_CONTEXT_ERROR: Failed to retrieve context
        """
        try:
            # Get the instrument
            instrument = graph_index.get_instrument(ticker.upper())
            if not instrument:
                return error_response(
                    error_code="INSTRUMENT_NOT_FOUND",
                    message=f"Instrument not found: {ticker}",
                    recovery_strategy="Check the ticker symbol and try again.",
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
                error_code="MARKET_CONTEXT_ERROR",
                message=f"Failed to get market context: {e!s}",
                recovery_strategy="Check the ticker and try again.",
            )

    @mcp.tool(
        name="get_instrument_news",
        description="Get news documents that affect a specific instrument, "
        "sorted by impact and recency. Useful for understanding what's driving price movements.",
    )
    def get_instrument_news(
        ticker: str,
        group_guids: list[str],
        days_back: int = 7,
        min_impact_score: float | None = None,
        limit: int = 20,
    ) -> ToolResponse:
        """Get news affecting an instrument.

        Args:
            ticker: Instrument ticker symbol (e.g., "AAPL")
            group_guids: List of group GUIDs for permission filtering
            days_back: Look back period in days (default: 7)
            min_impact_score: Minimum impact score (0-100)
            limit: Maximum number of documents (default: 20)

        Returns:
            JSON response with:
            - ticker: Instrument ticker
            - articles: List of documents with:
                - document_guid: Document identifier
                - title: Document title
                - impact_score: Impact score (0-100)
                - impact_tier: Impact tier
                - event_type: Event type if classified
                - magnitude: Impact magnitude on this instrument
                - direction: Impact direction (positive/negative/neutral)
                - created_at: Document timestamp
            - total_found: Total matching documents

        Errors:
            - INSTRUMENT_NOT_FOUND: Instrument doesn't exist
            - NEWS_QUERY_ERROR: Failed to retrieve news
        """
        try:
            # Verify instrument exists
            instrument = graph_index.get_instrument(ticker.upper())
            if not instrument:
                return error_response(
                    error_code="INSTRUMENT_NOT_FOUND",
                    message=f"Instrument not found: {ticker}",
                    recovery_strategy="Check the ticker symbol.",
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
                error_code="NEWS_QUERY_ERROR",
                message=f"Failed to get news: {e!s}",
                recovery_strategy="Check parameters and try again.",
            )
