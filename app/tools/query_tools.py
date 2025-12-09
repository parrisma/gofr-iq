"""MCP Query Tools - Phase 8 & 12.

Provides MCP tools for document retrieval and search.

Tools:
- get_document: Retrieve a document by its GUID
- query_documents: Search documents with semantic similarity and filters
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

from app.services.document_store import DocumentNotFoundError, DocumentStore
from app.services.query_service import QueryFilters, QueryService

if TYPE_CHECKING:
    pass

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def register_query_tools(
    mcp: FastMCP,
    document_store: DocumentStore,
    query_service: Optional[QueryService] = None,
) -> None:
    """Register query tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        document_store: DocumentStore for document retrieval
        query_service: QueryService for semantic search (optional)
    """

    @mcp.tool(
        name="get_document",
        description="Retrieve a document from the repository by its GUID. "
        "Returns the full document content and metadata.",
    )
    def get_document(
        guid: str,
        group_guid: str,
        date_hint: str | None = None,
    ) -> ToolResponse:
        """Get a document by its GUID.

        Args:
            guid: The document GUID to retrieve
            group_guid: The group GUID (required for access control and path resolution)
            date_hint: Optional date hint in YYYY-MM-DD format to speed up lookup.
                      If not provided, all date partitions will be searched.

        Returns:
            JSON response with full document data including:
            - guid: Document unique identifier
            - source_guid: Source that produced this document
            - group_guid: Owning group
            - title: Document title
            - content: Full document content
            - language: Document language code
            - language_detected: Whether language was auto-detected
            - word_count: Number of words
            - version: Document version number
            - duplicate_of: If duplicate, the original document GUID
            - duplicate_score: Similarity score if duplicate
            - created_at: Creation timestamp
            - updated_at: Last update timestamp
            - metadata: Additional document metadata

        Errors:
            - DOCUMENT_NOT_FOUND: The document doesn't exist or isn't accessible
        """
        try:
            # Parse date hint if provided
            date_obj: datetime | None = None
            if date_hint:
                try:
                    parsed_date = date.fromisoformat(date_hint)
                    # Convert date to datetime for the API
                    date_obj = datetime.combine(parsed_date, datetime.min.time())
                except ValueError:
                    return error_response(
                        error_code="INVALID_DATE",
                        message=f"Invalid date format: {date_hint}",
                        recovery_strategy="Use YYYY-MM-DD format for date_hint (e.g., '2025-12-08').",
                    )

            # Load document
            doc = document_store.load(guid, group_guid, date=date_obj)

            # Format full document response
            doc_data = {
                "guid": doc.guid,
                "source_guid": doc.source_guid,
                "group_guid": doc.group_guid,
                "title": doc.title,
                "content": doc.content,
                "language": doc.language,
                "language_detected": doc.language_detected,
                "word_count": doc.word_count,
                "version": doc.version,
                "duplicate_of": doc.duplicate_of,
                "duplicate_score": doc.duplicate_score,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "metadata": doc.metadata,
            }

            return success_response(data=doc_data)

        except DocumentNotFoundError:
            return error_response(
                error_code="DOCUMENT_NOT_FOUND",
                message=f"Document not found: {guid}",
                recovery_strategy="Verify the GUID is correct and you have access to the group. "
                "Provide a date_hint if you know the document's creation date.",
            )

        except Exception as e:
            return error_response(
                error_code="GET_DOCUMENT_ERROR",
                message=f"Failed to retrieve document: {e!s}",
                recovery_strategy="Check the GUID format and try again.",
            )

    # Only register query_documents if query_service is provided
    if query_service is not None:

        @mcp.tool(
            name="query_documents",
            description="Search documents using semantic similarity with optional filters. "
            "Returns ranked results based on relevance, trust scores, and recency. "
            "Supports impact-based filtering for high-impact news.",
        )
        def query_documents(
            query: str,
            group_guids: list[str],
            n_results: int = 10,
            regions: list[str] | None = None,
            sectors: list[str] | None = None,
            companies: list[str] | None = None,
            languages: list[str] | None = None,
            date_from: str | None = None,
            date_to: str | None = None,
            min_impact_score: float | None = None,
            impact_tiers: list[str] | None = None,
            event_types: list[str] | None = None,
            client_guid: str | None = None,
            include_graph_context: bool = True,
        ) -> ToolResponse:
            """Search documents using semantic similarity.

            Args:
                query: Natural language search query
                group_guids: List of group GUIDs the user has access to
                n_results: Maximum number of results to return (default: 10)
                regions: Filter by region codes (e.g., ["APAC", "EMEA"])
                sectors: Filter by sectors (e.g., ["Technology", "Finance"])
                companies: Filter by company tickers (e.g., ["AAPL", "MSFT"])
                languages: Filter by language codes (e.g., ["en", "zh"])
                date_from: Start date in YYYY-MM-DD format
                date_to: End date in YYYY-MM-DD format
                min_impact_score: Minimum impact score (0-100). Higher = more significant news.
                impact_tiers: Filter by impact tiers (e.g., ["PLATINUM", "GOLD"]).
                    Options: PLATINUM (>90), GOLD (70-89), SILVER (50-69), BRONZE (30-49), STANDARD (<30)
                event_types: Filter by event types (e.g., ["EARNINGS_BEAT", "M&A_ANNOUNCE"]).
                    Common types: EARNINGS_BEAT, EARNINGS_MISS, GUIDANCE_RAISE, GUIDANCE_CUT,
                    M&A_ANNOUNCE, M&A_RUMOR, ACTIVIST, FDA_APPROVAL, CENTRAL_BANK
                client_guid: Optional client GUID to personalize results based on portfolio/watchlist
                include_graph_context: Include related entities from graph (default: True)

            Returns:
                JSON response with:
                - query: Original query text
                - results: List of matching documents with:
                    - document_guid: Document identifier
                    - title: Document title
                    - content_snippet: Relevant excerpt
                    - score: Combined relevance score (0-1)
                    - similarity_score: Semantic similarity
                    - trust_score: Source trust contribution
                    - source_name: Source name
                    - language: Document language
                    - created_at: Creation timestamp
                    - impact_score: Impact score (0-100) if available
                    - impact_tier: Impact tier (PLATINUM/GOLD/SILVER/BRONZE/STANDARD)
                    - event_type: Event type code if classified
                    - graph_context: Related entities (if enabled)
                - total_found: Total matching documents
                - filters_applied: Active filters
                - execution_time_ms: Query execution time

            Errors:
                - QUERY_SERVICE_UNAVAILABLE: Search service is not configured
                - INVALID_DATE: Date format is invalid
                - QUERY_ERROR: Search failed
            """
            try:
                # Parse dates if provided
                date_from_obj: datetime | None = None
                date_to_obj: datetime | None = None

                if date_from:
                    try:
                        parsed = date.fromisoformat(date_from)
                        date_from_obj = datetime.combine(parsed, datetime.min.time())
                    except ValueError:
                        return error_response(
                            error_code="INVALID_DATE",
                            message=f"Invalid date_from format: {date_from}",
                            recovery_strategy="Use YYYY-MM-DD format (e.g., '2025-01-01').",
                        )

                if date_to:
                    try:
                        parsed = date.fromisoformat(date_to)
                        date_to_obj = datetime.combine(parsed, datetime.max.time())
                    except ValueError:
                        return error_response(
                            error_code="INVALID_DATE",
                            message=f"Invalid date_to format: {date_to}",
                            recovery_strategy="Use YYYY-MM-DD format (e.g., '2025-12-31').",
                        )

                # Build filters
                filters = QueryFilters(
                    date_from=date_from_obj,
                    date_to=date_to_obj,
                    regions=regions,
                    sectors=sectors,
                    companies=companies,
                    languages=languages,
                    min_impact_score=min_impact_score,
                    impact_tiers=impact_tiers,
                    event_types=event_types,
                    client_guid=client_guid,
                )

                # Execute query
                response = query_service.query(
                    query_text=query,
                    group_guids=group_guids,
                    n_results=n_results,
                    filters=filters,
                    include_graph_context=include_graph_context,
                )

                # Format results
                results_data = []
                for result in response.results:
                    result_item = {
                        "document_guid": result.document_guid,
                        "title": result.title,
                        "content_snippet": result.content_snippet,
                        "score": result.score,
                        "similarity_score": result.similarity_score,
                        "trust_score": result.trust_score,
                        "source_guid": result.source_guid,
                        "source_name": result.source_name,
                        "language": result.language,
                        "created_at": result.created_at.isoformat() if result.created_at else None,
                        "graph_context": result.graph_context,
                    }
                    # Add impact fields if available
                    if hasattr(result, "impact_score") and result.impact_score is not None:
                        result_item["impact_score"] = result.impact_score
                    if hasattr(result, "impact_tier") and result.impact_tier is not None:
                        result_item["impact_tier"] = result.impact_tier
                    if hasattr(result, "event_type") and result.event_type is not None:
                        result_item["event_type"] = result.event_type
                    results_data.append(result_item)

                return success_response(
                    data={
                        "query": response.query,
                        "results": results_data,
                        "total_found": response.total_found,
                        "filters_applied": response.filters_applied,
                        "execution_time_ms": response.execution_time_ms,
                    }
                )

            except Exception as e:
                return error_response(
                    error_code="QUERY_ERROR",
                    message=f"Search failed: {e!s}",
                    recovery_strategy="Check your query and filters, then try again.",
                )
