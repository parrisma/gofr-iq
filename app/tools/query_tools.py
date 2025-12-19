"""MCP Query Tools.

Provides document retrieval and semantic search.

Group Access Control:
    - Read operations use permitted groups from the authenticated token
    - Anonymous users can only access the public group
    - The group is extracted from the JWT token, not from client parameters
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Optional

from pydantic import Field

from gofr_common.mcp import error_response, success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

from app.services.document_store import DocumentNotFoundError, DocumentStore
from app.services.group_service import resolve_permitted_groups
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
            "Retrieve full document content by its GUID. "
            "USE FOR: Getting full text after finding document_guid from another tool. "
            "RETURNS: Full title, content, metadata, language, timestamps. "
            "PREREQUISITE: You need a document_guid (from query_documents, get_client_feed, etc). "
            "TIP: Provide date_hint (YYYY-MM-DD) if known for faster lookup."
        ),
    )
    def get_document(
        guid: Annotated[str, Field(
            min_length=36,
            max_length=36,
            pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            description="UUID of the document to retrieve",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        )],
        date_hint: Annotated[str | None, Field(
            default=None,
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            description="Document creation date in YYYY-MM-DD format to speed up lookup (optional)",
            examples=["2025-12-08", "2025-01-15"],
        )] = None,
        auth_tokens: Annotated[list[str] | None, Field(
            default=None,
            description="JWT tokens for authentication (pass via API when headers not available)",
        )] = None,
    ) -> ToolResponse:
        """Get a document by GUID.

        Access is limited to documents in groups you have permission to read.
        Anonymous users can only access documents in the public group.

        Args:
            guid: Document UUID (36-char format)
            date_hint: YYYY-MM-DD to speed up lookup (optional)

        Returns:
            Full document with:
            - guid: Document UUID
            - title, content: Document text
            - group_guid: Group name/identifier (string like 'reuters-feed')
            - metadata, timestamps, and other fields
        """
        try:
            # Get permitted groups from explicit tokens or context header
            permitted_groups = resolve_permitted_groups(auth_tokens=auth_tokens)

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

            # Load document with access check
            doc = document_store.load_with_access_check(
                guid=guid,
                permitted_groups=permitted_groups,
                date=date_obj,
            )

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
            error_msg = str(e)
            # Check for access denied errors
            if "access denied" in error_msg.lower():
                return error_response(
                    error_code="ACCESS_DENIED",
                    message=f"Access denied to document: {guid}",
                    recovery_strategy="You do not have permission to access this document's group.",
                )
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
                "Search news articles using natural language queries. "
                "USE FOR: 'Apple earnings', 'China tech regulation', 'M&A in APAC'. "
                "FILTERS: regions, sectors, companies (tickers), date range, impact level. "
                "RETURNS: Ranked articles with relevance scores, snippets, source info. "
                "DIFFERENT FROM get_instrument_news: This is topic search; that is ticker-specific."
            ),
        )
        def query_documents(
            query: Annotated[str, Field(
                min_length=1,
                max_length=1000,
                description="Natural language search query (e.g., 'earnings surprises', 'China tech regulation')",
            )],
            n_results: Annotated[int, Field(
                default=10,
                ge=1,
                le=100,
                description="Max results to return (default: 10, max: 100)",
            )] = 10,
            regions: Annotated[list[str] | None, Field(
                default=None,
                description="Filter by region codes: APAC, JP, CN, HK, SG, AU, KR, TW, US, EU",
            )] = None,
            sectors: Annotated[list[str] | None, Field(
                default=None,
                description="Filter by sector: Technology, Finance, Healthcare, Energy, Consumer, etc.",
            )] = None,
            companies: Annotated[list[str] | None, Field(
                default=None,
                description="Filter by ticker symbols: AAPL, 9988.HK, BABA, etc.",
            )] = None,
            languages: Annotated[list[str] | None, Field(
                default=None,
                description="Filter by language codes: en, zh, ja",
            )] = None,
            date_from: Annotated[str | None, Field(
                default=None,
                pattern=r"^\d{4}-\d{2}-\d{2}$",
                description="Start date filter in YYYY-MM-DD format",
                examples=["2025-01-01"],
            )] = None,
            date_to: Annotated[str | None, Field(
                default=None,
                pattern=r"^\d{4}-\d{2}-\d{2}$",
                description="End date filter in YYYY-MM-DD format",
                examples=["2025-12-31"],
            )] = None,
            min_impact_score: Annotated[float | None, Field(
                default=None,
                ge=0.0,
                le=100.0,
                description="Minimum importance score 0-100 (higher = bigger market impact)",
            )] = None,
            impact_tiers: Annotated[list[str] | None, Field(
                default=None,
                description="Filter by impact tier: PLATINUM, GOLD, SILVER, BRONZE, STANDARD",
            )] = None,
            event_types: Annotated[list[str] | None, Field(
                default=None,
                description="Filter by event type: EARNINGS_BEAT, EARNINGS_MISS, M&A_ANNOUNCE, FDA_APPROVAL, GUIDANCE_RAISE, GUIDANCE_CUT, etc.",
            )] = None,
            client_guid: Annotated[str | None, Field(
                default=None,
                min_length=36,
                max_length=36,
                description="Client UUID to personalize results for their portfolio/watchlist",
            )] = None,
            include_graph_context: Annotated[bool, Field(
                default=True,
                description="Include related entities from knowledge graph (default: True)",
            )] = True,
            auth_tokens: Annotated[list[str] | None, Field(
                default=None,
                description="JWT tokens for authentication (pass via API when headers not available)",
            )] = None,
        ) -> ToolResponse:
            """Search documents using natural language.

            Search is automatically limited to groups you have permission to access.
            Anonymous users can only search the public group.

            Args:
                query: What to search for (e.g., 'earnings surprises', 'China tech regulation')
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
                # Get permitted groups from explicit tokens or context header
                group_guids = resolve_permitted_groups(auth_tokens=auth_tokens)

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
