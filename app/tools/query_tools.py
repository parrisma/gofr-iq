"""MCP Query Tools.

Provides document retrieval and semantic search.
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
    """Register query tools with the MCP server."""

    @mcp.tool(
        name="get_document",
        description=(
            "Retrieve a specific document by ID. "
            "Use when you have a document_guid and need the full content."
        ),
    )
    def get_document(
        guid: str,
        group_guid: str,
        date_hint: str | None = None,
    ) -> ToolResponse:
        """Get a document by GUID.

        Args:
            guid: Document identifier
            group_guid: Group for access control
            date_hint: YYYY-MM-DD to speed up lookup (optional)

        Returns:
            Full document with title, content, metadata, timestamps
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
            description=(
                "Search news articles by topic, company, or event. "
                "Use for questions like 'What news about Apple?' or 'Recent M&A activity in APAC'. "
                "Returns ranked results with relevance scores."
            ),
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
            """Search documents using natural language.

            Args:
                query: What to search for (e.g., "earnings surprises", "China tech regulation")
                group_guids: Groups to search within
                n_results: Max results (default: 10)
                regions: Filter by region (APAC, JP, CN, HK, etc.)
                sectors: Filter by sector (Technology, Finance, Healthcare, etc.)
                companies: Filter by ticker (AAPL, 9988.HK, etc.)
                languages: Filter by language (en, zh, ja)
                date_from: Start date (YYYY-MM-DD)
                date_to: End date (YYYY-MM-DD)
                min_impact_score: Minimum importance 0-100 (higher = bigger market impact)
                impact_tiers: Filter by tier (PLATINUM/GOLD/SILVER/BRONZE/STANDARD)
                event_types: Filter by event (EARNINGS_BEAT, M&A_ANNOUNCE, FDA_APPROVAL, etc.)
                client_guid: Personalize results for this client's portfolio/watchlist
                include_graph_context: Include related entities (default: True)

            Returns:
                results: Ranked articles with title, snippet, scores, source, timestamps
                total_found: Total matches
                execution_time_ms: Query time
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
