"""GOFR-IQ MCP Server Implementation.

This module provides the MCP server implementation for the APAC Brokerage News Repository.
The server exposes tools for document ingestion, source management, and document retrieval.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mcp.server.fastmcp import FastMCP

from app.config import get_config, GofrIqConfig
from app.logger import session_logger
from app.services import (
    DocumentStore,
    DuplicateDetector,
    EmbeddingIndex,
    GraphIndex,
    IngestService,
    LanguageDetector,
    LLMService,
    QueryService,
    SourceRegistry,
)
from app.tools import register_all_tools

if TYPE_CHECKING:
    pass


def create_mcp_server(
    storage_dir: str | Path | None = None,
    mcp_port: int | None = None,
    host: str = "0.0.0.0",  # nosec B104
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
    require_auth: bool = True,
    config: GofrIqConfig | None = None,
) -> FastMCP:
    """Create and configure the MCP server.

    Args:
        storage_dir: Override storage directory (uses config if not provided)
        mcp_port: Override MCP port (uses config if not provided)
        host: Host to bind to (default: 0.0.0.0)
        log_level: Logging level (default: INFO)
        require_auth: Whether authentication is required (default: True)
        config: GofrIqConfig instance (loads from env if not provided)

    Returns:
        Configured FastMCP server instance
    """
    # Get configuration
    if config is None:
        config = get_config()

    # Use overrides or config
    storage_path = Path(storage_dir) if storage_dir else config.project_root / "data" / "storage"
    port = mcp_port or int(os.getenv("GOFR_IQ_MCP_PORT", "8080"))

    # Initialize services
    document_store = DocumentStore(base_path=storage_path / "documents")
    source_registry = SourceRegistry(base_path=storage_path / "sources")
    language_detector = LanguageDetector()
    duplicate_detector = DuplicateDetector()

    # Initialize indexes using config
    if config.chromadb_is_http_mode:
        # HTTP client mode - connect to ChromaDB server
        embedding_index = EmbeddingIndex(
            host=config.chroma_host,
            port=config.chroma_port,
        )
    else:
        # ChromaDB HTTP server MUST be configured - no local fallback
        # This prevents silent state divergence between containers
        raise RuntimeError(
            "ChromaDB HTTP server not configured. "
            "GOFR_IQ_CHROMADB_HOST must be set to use shared ChromaDB server. "
            f"Current: GOFR_IQ_CHROMADB_HOST={os.getenv('GOFR_IQ_CHROMADB_HOST')} "
            f"Environment: {os.getenv('GOFR_IQ_ENV', 'PROD')}"
        )
    
    # Graph index requires Neo4j connection
    # We initialize it but handle connection errors gracefully in service
    graph_index = GraphIndex()

    # Create LLM service with config
    # CRITICAL: OpenRouter API key MUST be set for entity extraction to work
    openrouter_key = os.getenv("GOFR_IQ_OPENROUTER_API_KEY")
    if not openrouter_key:
        session_logger.error(
            "FATAL: GOFR_IQ_OPENROUTER_API_KEY not set. "
            "LLM service is required for entity extraction when graph index is enabled."
        )
        raise ValueError(
            "GOFR_IQ_OPENROUTER_API_KEY must be set in environment. "
            "Check docker/.env or run bootstrap.py --openrouter-key YOUR_KEY"
        )
    
    llm_service = LLMService(config=config)
    session_logger.info("LLMService initialized with OpenRouter API key")

    ingest_service = IngestService(
        document_store=document_store,
        source_registry=source_registry,
        language_detector=language_detector,
        duplicate_detector=duplicate_detector,
        embedding_index=embedding_index,
        graph_index=graph_index,
        llm_service=llm_service,
    )

    # Create query service for semantic search
    query_service = QueryService(
        embedding_index=embedding_index,
        document_store=document_store,
        source_registry=source_registry,
        graph_index=graph_index,
    )

    # Create MCP server
    server = FastMCP(
        name="gofr-iq",
        instructions="""GOFR-IQ is an APAC Brokerage News Repository MCP server.

Available tools:
- ingest_document: Ingest news documents with validation and language detection
- query_documents: Search for news articles by topic, company, or event
- list_sources: List registered news sources with optional filtering
- get_source: Get detailed information about a specific source
- create_source: Register a new news source
- get_document: Retrieve a document by its GUID
- health_check: Check health of Neo4j, ChromaDB, and LLM API connections

All documents are scoped by group_guid for access control.""",
        port=port,
        host=host,
        log_level=log_level,
    )

    # Register all tools
    register_all_tools(
        mcp=server,
        document_store=document_store,
        source_registry=source_registry,
        ingest_service=ingest_service,
        query_service=query_service,
        graph_index=graph_index,
        embedding_index=embedding_index,
        llm_service=llm_service,
    )

    return server
