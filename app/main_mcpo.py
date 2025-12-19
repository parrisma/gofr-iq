#!/usr/bin/env python3
"""Main entry point for MCPO wrapper.

Starts MCPO proxy to expose GOFR-IQ MCP server as OpenAPI endpoints.

Usage:
    # Start with no authentication on MCPO layer (MCP handles JWT auth):
    python -m app.main_mcpo

    # Start with MCPO API key authentication:
    export GOFR_IQ_MCPO_API_KEY="your-api-key"
    python -m app.main_mcpo

    # Start with authenticated mode (pass JWT token through to MCP):
    export GOFR_IQ_JWT_TOKEN="your-jwt-token"
    export GOFR_IQ_MCPO_MODE="auth"
    python -m app.main_mcpo

Environment Variables:
    GOFR_IQ_MCP_PORT: Port for MCP server (from gofr-common config)
    GOFR_IQ_MCPO_PORT: Port for MCPO proxy (from gofr-common config)
    GOFR_IQ_MCPO_API_KEY: Optional API key for MCPO authentication
    GOFR_IQ_JWT_TOKEN: Optional JWT token for MCP server authentication
    GOFR_IQ_MCPO_MODE: 'auth' or 'public' (default: public)
"""

import asyncio
import os
import signal
import sys

from app.mcpo_server.wrapper import start_mcpo_wrapper

# Import canonical port configuration from gofr-common
try:
    from gofr_common.config import GOFR_IQ_PORTS
    DEFAULT_MCP_PORT = GOFR_IQ_PORTS.mcp
    DEFAULT_MCPO_PORT = GOFR_IQ_PORTS.mcpo
except ImportError:
    # Fallback if gofr-common not available
    import os
    DEFAULT_MCP_PORT = int(os.environ.get("GOFR_IQ_MCP_PORT", 8080))
    DEFAULT_MCPO_PORT = int(os.environ.get("GOFR_IQ_MCPO_PORT", 8081))


def main():
    """Main function to start MCPO wrapper."""

    # Get configuration from environment (defaults from gofr-common)
    mcp_host = os.environ.get("GOFR_IQ_MCP_HOST", "localhost")
    mcp_port = int(os.environ.get("GOFR_IQ_MCP_PORT", str(DEFAULT_MCP_PORT)))
    mcpo_port = int(os.environ.get("GOFR_IQ_MCPO_PORT", str(DEFAULT_MCPO_PORT)))

    auth_disabled = os.environ.get("GOFR_IQ_AUTH_DISABLED", "false").lower() in ("1", "true", "yes")
    print(f"[MCPO] Starting on host=0.0.0.0 port={mcpo_port}")
    print(f"[MCPO] Connecting to MCP at http://{mcp_host}:{mcp_port}/mcp")
    print(f"[MCPO] Proxy available at http://localhost:{mcpo_port}")
    print(f"[MCPO] Startup: auth_disabled={auth_disabled}")

    # Check for API key
    mcpo_api_key = os.environ.get("GOFR_IQ_MCPO_API_KEY")
    if mcpo_api_key:
        print(f"  MCPO API Key: {'*' * 8} (from GOFR_IQ_MCPO_API_KEY)")
    else:
        print("  MCPO API Key: None (no authentication required)")

    # Check for auth mode
    mode = os.environ.get("GOFR_IQ_MCPO_MODE", "public").lower()
    if mode == "auth":
        jwt_token = os.environ.get("GOFR_IQ_JWT_TOKEN")
        if jwt_token:
            print("  Mode: Authenticated (JWT token will be passed to MCP)")
        else:
            print("  Mode: Authenticated (but GOFR_IQ_JWT_TOKEN not set - will fail)")
    else:
        print("  Mode: Public (no JWT token passed to MCP)")

    # Start the wrapper
    wrapper = start_mcpo_wrapper(
        mcp_host=mcp_host,
        mcp_port=mcp_port,
        mcpo_port=mcpo_port,
    )

    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}, shutting down MCPO wrapper...")
        wrapper.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("\nMCPO proxy is running!")
    print(f"  Health check: curl http://localhost:{mcpo_port}/health")
    print(f"  OpenAPI spec: curl http://localhost:{mcpo_port}/openapi.json")
    print(f"  List tools: curl http://localhost:{mcpo_port}/tools/list")
    print("\nPress Ctrl+C to stop...")

    try:
        # Run the wrapper
        asyncio.run(wrapper.run_async())
    except KeyboardInterrupt:
        print("\nShutting down MCPO wrapper...")
        wrapper.stop()
    except Exception as e:
        print(f"Error running MCPO wrapper: {e}")
        wrapper.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
