"""GOFR-IQ MCP Server - Main Entry Point.

This module provides the MCP server for the APAC Brokerage News Repository.
The server exposes tools for document ingestion, source management, and document retrieval.

Usage:
    # Run with uvicorn (for SSE transport)
    uvicorn app.main:mcp.app --host 0.0.0.0 --port 8060

    # Or use the mcp module directly
    python -m app.main

Environment Variables:
    GOFRIQ_STORAGE_DIR: Base directory for document storage (default: ./data/storage)
    GOFRIQ_MCP_PORT: Port for MCP server (default: 8060)
    GOFRIQ_LOG_LEVEL: Logging level (default: INFO)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.services import (
    DocumentStore,
    DuplicateDetector,
    EmbeddingIndex,
    GraphIndex,
    IngestService,
    LanguageDetector,
    SourceRegistry,
)
from app.tools import register_all_tools

if TYPE_CHECKING:
    pass


def create_mcp_server(
    storage_dir: str | Path | None = None,
    mcp_port: int | None = None,
) -> FastMCP:
    """Create and configure the MCP server.

    Args:
        storage_dir: Override storage directory (uses config if not provided)
        mcp_port: Override MCP port (uses config if not provided)

    Returns:
        Configured FastMCP server instance
    """
    # Get configuration
    settings = get_settings()

    # Use overrides or settings
    storage_path = Path(storage_dir) if storage_dir else settings.storage.storage_dir
    port = mcp_port or settings.server.mcp_port

    # Initialize services
    document_store = DocumentStore(base_path=storage_path / "documents")
    source_registry = SourceRegistry(base_path=storage_path / "sources")
    language_detector = LanguageDetector()
    duplicate_detector = DuplicateDetector()

    # Initialize indexes
    # Note: In production, these would connect to real services
    # For now, we use defaults (ephemeral/local) or env vars
    embedding_index = EmbeddingIndex(
        persist_directory=storage_path / "chroma",
    )
    
    # Graph index requires Neo4j connection
    # We initialize it but handle connection errors gracefully in service
    graph_index = GraphIndex()

    ingest_service = IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=language_detector,
        duplicate_detector=duplicate_detector,
        embedding_index=embedding_index,
        graph_index=graph_index,
    )

    # Create MCP server
    server = FastMCP(
        name="gofr-iq",
        instructions="""GOFR-IQ is an APAC Brokerage News Repository MCP server.

Available tools:
- ingest_document: Ingest news documents with validation and language detection
- list_sources: List registered news sources with optional filtering
- get_source: Get detailed information about a specific source
- get_document: Retrieve a document by its GUID

All documents are scoped by group_guid for access control.""",
        port=port,
        host="0.0.0.0",
        log_level="INFO",
    )

    # Register all tools
    register_all_tools(
        mcp=server,
        document_store=document_store,
        source_registry=source_registry,
        ingest_service=ingest_service,
    )

    return server


# Create default server instance
mcp = create_mcp_server()


def main() -> None:
    """Run the MCP server."""
    settings = get_settings()

    print(f"Starting GOFR-IQ MCP Server on port {settings.server.mcp_port}...")
    print(f"Storage directory: {settings.storage.storage_dir}")
    print("Press Ctrl+C to stop")

    try:
        mcp.run()
    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
