"""MCP Tools for GOFR-IQ.

This module provides MCP tool implementations for the news repository system.
Tools are organized by functionality:

- ingest_tools: Document ingestion operations
- source_tools: Source registry operations (list, get, create)
- query_tools: Document retrieval and search
- health_tools: Infrastructure health checks
- client_tools: Client management and personalized feeds
- graph_tools: Knowledge graph exploration

Usage:
    from app.tools import register_all_tools

    mcp = FastMCP("gofr-iq")
    register_all_tools(mcp, services)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.tools.client_tools import register_client_tools
from app.tools.graph_tools import register_graph_tools
from app.tools.health_tools import register_health_tools
from app.tools.ingest_tools import register_ingest_tools
from app.tools.query_tools import register_query_tools
from app.tools.source_tools import register_source_tools

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from app.services import DocumentStore, IngestService, QueryService, SourceRegistry
    from app.services.embedding_index import EmbeddingIndex
    from app.services.graph_index import GraphIndex
    from app.services.llm_service import LLMService

__all__ = [
    "register_ingest_tools",
    "register_source_tools",
    "register_query_tools",
    "register_health_tools",
    "register_client_tools",
    "register_graph_tools",
    "register_all_tools",
]


def register_all_tools(
    mcp: "FastMCP",
    document_store: "DocumentStore",
    source_registry: "SourceRegistry",
    ingest_service: "IngestService",
    query_service: "Optional[QueryService]" = None,
    graph_index: "Optional[GraphIndex]" = None,
    embedding_index: "Optional[EmbeddingIndex]" = None,
    llm_service: "Optional[LLMService]" = None,
) -> None:
    """Register all MCP tools with the server.

    Args:
        mcp: FastMCP server instance
        document_store: DocumentStore instance for document operations
        source_registry: SourceRegistry instance for source operations
        ingest_service: IngestService instance for ingestion operations
        query_service: QueryService instance for search operations (optional)
        graph_index: GraphIndex instance for Neo4j connectivity (optional)
        embedding_index: EmbeddingIndex instance for ChromaDB connectivity (optional)
        llm_service: LLMService instance for LLM API connectivity (optional)
    """
    register_ingest_tools(mcp, ingest_service)
    register_source_tools(mcp, source_registry)
    register_query_tools(mcp, document_store, query_service)
    register_health_tools(mcp, graph_index, embedding_index, llm_service)
    
    # Register client and graph tools if graph_index is available
    if graph_index is not None:
        register_client_tools(mcp, graph_index)
        register_graph_tools(mcp, graph_index)
