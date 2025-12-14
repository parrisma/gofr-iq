"""MCP Health Tools.

Provides system health check operations for infrastructure dependencies.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from gofr_common.mcp import success_response
from mcp.server.fastmcp import FastMCP
from mcp.types import EmbeddedResource, ImageContent, TextContent

if TYPE_CHECKING:
    from app.services.embedding_index import EmbeddingIndex
    from app.services.graph_index import GraphIndex
    from app.services.llm_service import LLMService

# Type alias for MCP tool response
ToolResponse = Sequence[TextContent | ImageContent | EmbeddedResource]


def register_health_tools(
    mcp: FastMCP,
    graph_index: "GraphIndex | None" = None,
    embedding_index: "EmbeddingIndex | None" = None,
    llm_service: "LLMService | None" = None,
) -> None:
    """Register health check tools with the MCP server.
    
    Args:
        mcp: FastMCP server instance
        graph_index: GraphIndex instance for Neo4j connectivity
        embedding_index: EmbeddingIndex instance for ChromaDB connectivity
        llm_service: LLMService instance for LLM API connectivity
    """

    @mcp.tool(
        name="health_check",
        description=(
            "Check the health of all infrastructure dependencies. "
            "Returns status of Neo4j, ChromaDB, and LLM API connections."
        ),
    )
    def health_check() -> ToolResponse:
        """Check health of all infrastructure dependencies.

        Returns:
            status: Overall health status (healthy, degraded, unhealthy)
            services: Individual service statuses with details
            timestamp: When the check was performed
        """
        from datetime import datetime, timezone

        services: dict[str, Any] = {}
        all_healthy = True
        any_healthy = False

        # Check Neo4j (Graph Index)
        neo4j_status = _check_neo4j(graph_index)
        services["neo4j"] = neo4j_status
        if neo4j_status["status"] == "healthy":
            any_healthy = True
        else:
            all_healthy = False

        # Check ChromaDB (Embedding Index)
        chroma_status = _check_chromadb(embedding_index)
        services["chromadb"] = chroma_status
        if chroma_status["status"] == "healthy":
            any_healthy = True
        else:
            all_healthy = False

        # Check LLM API
        llm_status = _check_llm(llm_service)
        services["llm"] = llm_status
        if llm_status["status"] == "healthy":
            any_healthy = True
        else:
            all_healthy = False

        # Determine overall status
        if all_healthy:
            overall_status = "healthy"
            message = "All services are operational"
        elif any_healthy:
            overall_status = "degraded"
            unhealthy = [k for k, v in services.items() if v["status"] != "healthy"]
            message = f"Some services unavailable: {', '.join(unhealthy)}"
        else:
            overall_status = "unhealthy"
            message = "All services are unavailable"

        return success_response(
            data={
                "status": overall_status,
                "message": message,
                "services": services,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


def _check_neo4j(graph_index: "GraphIndex | None") -> dict[str, Any]:
    """Check Neo4j connectivity and status."""
    if graph_index is None:
        return {
            "status": "unavailable",
            "message": "GraphIndex not configured",
            "connected": False,
        }

    try:
        # Try to verify connectivity
        connected = graph_index.verify_connectivity()
        if connected:
            # Get node count as additional health indicator
            try:
                node_count = graph_index.count_nodes()
                return {
                    "status": "healthy",
                    "message": "Connected to Neo4j",
                    "connected": True,
                    "node_count": node_count,
                }
            except Exception:
                return {
                    "status": "healthy",
                    "message": "Connected to Neo4j (count unavailable)",
                    "connected": True,
                }
        else:
            return {
                "status": "unhealthy",
                "message": "Neo4j connection failed",
                "connected": False,
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Neo4j error: {e!s}",
            "connected": False,
        }


def _check_chromadb(embedding_index: "EmbeddingIndex | None") -> dict[str, Any]:
    """Check ChromaDB connectivity and status."""
    if embedding_index is None:
        return {
            "status": "unavailable",
            "message": "EmbeddingIndex not configured",
            "connected": False,
        }

    try:
        # Try to get collection info - this verifies connectivity
        collection = embedding_index.collection
        if collection is not None:
            # Get document count
            try:
                doc_count = embedding_index.count()
                return {
                    "status": "healthy",
                    "message": "Connected to ChromaDB",
                    "connected": True,
                    "collection_name": collection.name,
                    "document_count": doc_count,
                }
            except Exception:
                return {
                    "status": "healthy",
                    "message": "Connected to ChromaDB (count unavailable)",
                    "connected": True,
                    "collection_name": collection.name,
                }
        else:
            return {
                "status": "unhealthy",
                "message": "ChromaDB collection not initialized",
                "connected": False,
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"ChromaDB error: {e!s}",
            "connected": False,
        }


def _check_llm(llm_service: "LLMService | None") -> dict[str, Any]:
    """Check LLM API connectivity and configuration."""
    if llm_service is None:
        return {
            "status": "unavailable",
            "message": "LLMService not configured",
            "configured": False,
            "api_key_set": False,
        }

    try:
        # Check if API key is configured
        # Handle both property (real LLMService) and mock method patterns
        is_available_attr = getattr(llm_service, 'is_available', None)
        if hasattr(is_available_attr, '__call__') and not isinstance(is_available_attr, bool):
            is_available = is_available_attr()  # type: ignore[misc]
        else:
            is_available = bool(is_available_attr)
        
        if not is_available:
            return {
                "status": "unavailable",
                "message": "LLM API key not configured",
                "configured": False,
                "api_key_set": False,
            }

        # Get model info from settings
        settings = llm_service.settings
        return {
            "status": "healthy",
            "message": "LLM API configured and ready",
            "configured": True,
            "api_key_set": True,
            "chat_model": settings.chat_model if settings else "unknown",
            "embedding_model": settings.embedding_model if settings else "unknown",
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"LLM error: {e!s}",
            "configured": False,
        }
