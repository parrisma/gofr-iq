"""MCP Tools for GOFR-IQ.

This module provides MCP tool implementations for the news repository system.
Tools are organized by functionality:

- ingest_tools: Document ingestion operations
- source_tools: Source registry operations
- query_tools: Document retrieval and search

Usage:
    from app.tools import register_all_tools

    mcp = FastMCP("gofr-iq")
    register_all_tools(mcp, services)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.tools.ingest_tools import register_ingest_tools
from app.tools.query_tools import register_query_tools
from app.tools.source_tools import register_source_tools

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from app.services import DocumentStore, IngestService, SourceRegistry

__all__ = [
    "register_ingest_tools",
    "register_source_tools",
    "register_query_tools",
    "register_all_tools",
]


def register_all_tools(
    mcp: "FastMCP",
    document_store: "DocumentStore",
    source_registry: "SourceRegistry",
    ingest_service: "IngestService",
) -> None:
    """Register all MCP tools with the server.

    Args:
        mcp: FastMCP server instance
        document_store: DocumentStore instance for document operations
        source_registry: SourceRegistry instance for source operations
        ingest_service: IngestService instance for ingestion operations
    """
    register_ingest_tools(mcp, ingest_service)
    register_source_tools(mcp, source_registry)
    register_query_tools(mcp, document_store)
