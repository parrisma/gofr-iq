"""GOFR-IQ MCP Server - Main Entry Point.

This module provides the main entry point for the MCP server.
The server exposes tools for document ingestion, source management, and document retrieval.

Usage:
    # Run with standard options
    python -m app.main_mcp

    # Run with custom host and port
    python -m app.main_mcp --host 0.0.0.0 --port ${GOFR_IQ_MCP_PORT:-8080}

    # Run without authentication (development only)
    python -m app.main_mcp --no-auth

Environment Variables:
    GOFR_IQ_STORAGE_DIR: Base directory for document storage
    GOFR_IQ_MCP_PORT: Port for MCP server (from gofr-common config)
    GOFR_IQ_LOG_LEVEL: Logging level (default: INFO)
    GOFR_IQ_AUTH_ENABLED: Enable/disable authentication (default: true)
    GOFR_IQ_JWT_SECRET: JWT secret for authentication
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys
from pathlib import Path

import uvicorn

from app.config import get_settings
from app.logger import ConsoleLogger
from app.mcp_server.mcp_server import create_mcp_server
from gofr_common.web import create_mcp_starlette_app

logger = ConsoleLogger(name="main_mcp", level=logging.INFO)

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="gofr-iq MCP Server - APAC Brokerage News Repository"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("GOFR_IQ_MCP_HOST", "0.0.0.0"),
        help="Host address to bind to (default: from env or 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("GOFR_IQ_MCP_PORT", 8080)),
        help="Port number to listen on (default: from env or gofr-common config)",
    )
    parser.add_argument(
        "--auth-disabled",
        action="store_true",
        default=os.environ.get("GOFR_IQ_AUTH_DISABLED", "true").lower() in ("1", "true", "yes"),
        help="Disable authentication (default: true, can be overridden by GOFR_IQ_AUTH_DISABLED)",
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
        help="JWT secret key (default: from GOFR_IQ_JWT_SECRET env var)",
    )
    parser.add_argument(
        "--token-store",
        type=str,
        default=None,
        help="Path to token store file (default: {data_dir}/auth/tokens.json)",
    )
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

    # Explicitly log host/port for debugging
    print(f"[MCP] Startup: host={args.host or os.environ.get('GOFR_IQ_MCP_HOST', '0.0.0.0')} port={args.port or os.environ.get('GOFR_IQ_MCP_PORT', 8080)} auth_disabled={args.auth_disabled}")

    # Parse log level
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)

    # Create logger for startup messages
    startup_logger = ConsoleLogger(name="startup", level=log_level)

    try:
        # Resolve authentication configuration
        jwt_secret = args.jwt_secret or os.getenv("GOFR_IQ_JWT_SECRET")
        token_store_path = args.token_store or os.getenv("GOFR_IQ_TOKEN_STORE")
        
        # Determine auth requirement
        # Check command line first, then environment variable
        if args.no_auth:
            require_auth = False
            startup_logger.warning("Authentication disabled via --no-auth flag")
        else:
            # Check environment variable
            auth_enabled = os.environ.get("GOFR_IQ_AUTH_ENABLED", "true").lower()
            require_auth = auth_enabled not in ("false", "0", "no")
            if not require_auth:
                startup_logger.warning("Authentication disabled via GOFR_IQ_AUTH_ENABLED")
            
            # Auto-generate secret for development if not provided
            if require_auth and not jwt_secret:
                env = os.getenv("GOFR_IQ_ENV", os.getenv("GOFR_IQ_ENV", "PROD"))
                if env.upper() not in ["PROD", "PRODUCTION"]:
                    jwt_secret = f"dev-secret-{secrets.token_hex(16)}"
                    startup_logger.info("Auto-generated development JWT secret")
                else:
                    startup_logger.error(
                        "FATAL: JWT secret required in production",
                        help="Set GOFR_IQ_JWT_SECRET environment variable or use --jwt-secret flag",
                    )
                    sys.exit(1)

        # Build settings from environment and CLI args
        settings = get_settings(require_auth=False)

        # Override with CLI arguments if provided
        host = args.host or os.environ.get("GOFR_IQ_MCP_HOST", "0.0.0.0")  # nosec B104
        port = args.port or settings.server.mcp_port
        storage_dir = args.storage_dir or settings.storage.storage_dir

        # Use resolved auth configuration
        if require_auth:
            settings.auth.jwt_secret = jwt_secret
            settings.auth.token_store_path = Path(token_store_path) if token_store_path else None
            settings.auth.require_auth = True

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

        print(f"Starting GOFR-IQ MCP Server on {host}:{port}...")
        print(f"Storage directory: {storage_dir}")
        print(f"Authentication: {'Enabled' if require_auth else 'Disabled'}")
        print("Transport: HTTP Streamable")
        print("Press Ctrl+C to stop")
        print()

        # Get the streamable HTTP handler from FastMCP
        mcp_handler = mcp.streamable_http_app()
        
        # For now, use the handler directly without Starlette wrapping
        # TODO: Re-enable auth middleware for group extraction
        app = mcp_handler

        # Run with uvicorn directly instead of FastMCP.run()
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=args.log_level.lower(),
        )

    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)
    except Exception as e:
        startup_logger.error("FATAL: Failed to start MCP server", error=str(e))
        sys.exit(1)
