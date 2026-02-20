"""GOFR-IQ MCP Server - Main Entry Point.

This module provides the main entry point for the MCP server.
The server exposes tools for document ingestion, source management, and document retrieval.

Usage:
    # Run with standard options
    python -m app.main_mcp

    # Run with custom host and port (port from gofr_ports.sh or explicit)
    python -m app.main_mcp --host 0.0.0.0 --port ${GOFR_IQ_MCP_PORT}

    # Run without authentication (development only)
    python -m app.main_mcp --no-auth

Environment Variables:
    GOFR_IQ_STORAGE_DIR: Base directory for document storage
    GOFR_IQ_MCP_PORT: Port for MCP server (required - from gofr_ports.sh)
    GOFR_IQ_LOG_LEVEL: Logging level (default: INFO)
    GOFR_IQ_AUTH_ENABLED: Enable/disable authentication (default: true)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

from app.auth.factory import create_auth_service
from app.config import get_config
from app.logger import ConsoleLogger
from app.mcp_server.mcp_server import create_mcp_server
from app.services.group_service import init_group_service

logger = ConsoleLogger(name="main_mcp", level=logging.INFO)

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="gofr-iq MCP Server - APAC Brokerage News Repository"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("GOFR_IQ_MCP_HOST", "0.0.0.0"),  # nosec B104 - intentional for container/server deployment
        help="Host address to bind to (default: from env or 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ["GOFR_IQ_MCP_PORT"]) if "GOFR_IQ_MCP_PORT" in os.environ else None,
        help="Port number to listen on (required: set GOFR_IQ_MCP_PORT or use --port)",
    )
    parser.add_argument(
        "--auth-disabled",
        action="store_true",
        default=os.environ.get("GOFR_IQ_AUTH_DISABLED", "false").lower() in ("1", "true", "yes"),
        help="Disable authentication (default: false, auth enabled by default)",
    )
    parser.add_argument(
        "--storage-dir",
        type=str,
        default=None,
        help="Storage directory for documents (default: from env)",
    )
    parser.add_argument(
        "--jwt-secret",
        type=str,
        default=None,
        help=argparse.SUPPRESS,
    )
    # NOTE: backend configured via GOFR_IQ_AUTH_BACKEND/GOFR_IQ_VAULT_* env vars
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable authentication (WARNING: insecure, for development only)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Logging level for all components (default: INFO)",
    )
    args = parser.parse_args()
    
    # Parse log level first (needed for logger initialization)
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)

    # Create logger for startup messages
    startup_logger = ConsoleLogger(name="startup", level=log_level)
    
    # Validate required port
    if args.port is None:
        parser.error("Port is required: set GOFR_IQ_MCP_PORT environment variable or use --port")

    # Explicitly log host/port for debugging
    # B104: Intentional 0.0.0.0 binding for containerized services (accepts external connections)
    startup_logger.info(
        f"MCP Startup: host={args.host or os.environ.get('GOFR_IQ_MCP_HOST', '0.0.0.0')} "  # nosec B104
        f"port={args.port or os.environ.get('GOFR_IQ_MCP_PORT', 8080)} auth_disabled={args.auth_disabled}"
    )

    try:
        # Determine auth requirement
        # Check command line flags first (--no-auth or --auth-disabled), then environment variable
        if args.no_auth or args.auth_disabled:
            require_auth = False
            if args.no_auth:
                startup_logger.warning("Authentication disabled via --no-auth flag")
            else:
                startup_logger.warning("Authentication disabled via --auth-disabled flag or GOFR_IQ_AUTH_DISABLED env")
        else:
            # Check environment variable
            auth_enabled = os.environ.get("GOFR_IQ_AUTH_ENABLED", "true").lower()
            require_auth = auth_enabled not in ("false", "0", "no")
            if not require_auth:
                startup_logger.warning("Authentication disabled via GOFR_IQ_AUTH_ENABLED")
            
        # Load configuration from environment
        config = get_config()

        # Override with CLI arguments if provided
        host = args.host or os.environ.get("GOFR_IQ_MCP_HOST", "0.0.0.0")  # nosec B104
        
        # Get port from environment (GOFR_IQ_MCP_PORT set by run script)
        port = args.port
        if port is None:
            port_str = os.environ.get("GOFR_IQ_MCP_PORT")
            if port_str:
                port = int(port_str)
            else:
                startup_logger.error("Port required: set GOFR_IQ_MCP_PORT or use --port")
                sys.exit(1)
        
        storage_dir = args.storage_dir or config.project_root / "data" / "storage"

        # Use resolved auth configuration
        auth_service = None
        if require_auth:
            # Create AuthService via Vault-backed secret provider + stores
            auth_service = create_auth_service(prefix="GOFR_IQ", audience="gofr-api")
            backend = os.getenv("GOFR_IQ_AUTH_BACKEND", os.getenv("GOFR_AUTH_BACKEND", "vault"))
            startup_logger.info(
                "AuthService initialized",
                backend=backend,
                secret_fingerprint=auth_service.get_secret_fingerprint(),
            )
        
        # Initialize GroupService with AuthService for JWT-based group extraction
        # This enables get_permitted_groups_from_context() in MCP tools
        init_group_service(auth_service=auth_service)
        startup_logger.info(
            "GroupService initialized",
            auth_enabled=auth_service is not None,
        )

        startup_logger.info(
            "Starting GOFR-IQ MCP Server",
            host=host,
            port=port,
            storage_dir=str(storage_dir),
            auth_enabled=require_auth,
            log_level=args.log_level,
        )

        # Create and run server
        mcp = create_mcp_server(
            storage_dir=storage_dir,
            mcp_port=port,
            host=host,
            log_level=args.log_level,
            require_auth=require_auth,
        )

        startup_logger.info(f"Starting GOFR-IQ MCP Server on {host}:{port}...")
        startup_logger.info(f"Storage directory: {storage_dir}")
        startup_logger.info(f"Authentication: {'Enabled' if require_auth else 'Disabled'}")
        startup_logger.info("Transport: HTTP Streamable")
        startup_logger.info("Press Ctrl+C to stop")

        # Get the Starlette app from FastMCP
        # This app includes the proper lifespan context for MCP sessions
        from gofr_common.web import AuthHeaderMiddleware
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        
        app = mcp.streamable_http_app()
        
        # Add a simple /health endpoint for healthchecks
        # (MCP streamable HTTP is session-based, can't healthcheck /mcp directly)
        async def health_endpoint(request):
            return JSONResponse({"status": "ok", "service": "gofr-iq-mcp"})
        
        app.routes.append(Route("/health", health_endpoint, methods=["GET"]))
        
        # Add AuthHeaderMiddleware to extract JWT from headers
        # This stores the Authorization header in a ContextVar for use by
        # get_permitted_groups_from_context() in MCP tools
        app.add_middleware(AuthHeaderMiddleware)  # type: ignore[arg-type]
        
        startup_logger.info(
            "AuthHeaderMiddleware enabled for group-based access control"
        )

        # Run with uvicorn directly (FastMCP.run() doesn't allow adding middleware)
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=args.log_level.lower(),
        )

    except KeyboardInterrupt:
        startup_logger.info("Server stopped")
        sys.exit(0)
    except Exception as e:
        startup_logger.error(
            "FATAL: Failed to start MCP server",
            cause_type=type(e).__name__,
            error=str(e),
            remediation="Review logs and Vault configuration, then retry",
        )
        sys.exit(1)
