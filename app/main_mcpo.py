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
import json
import os
import signal
import sys
import urllib.request

from app.mcpo_server.wrapper import start_mcpo_wrapper

# Ports must be set via environment variables - no defaults

def _get_required_port(env_var: str) -> int:
    """Get required port from environment or raise error."""
    value = os.environ.get(env_var)
    if value is None:
        raise ValueError(f"Required environment variable {env_var} is not set")
    return int(value)


def main():
    """Main function to start MCPO wrapper."""

    # Get configuration from environment (required - no defaults)
    mcp_host = os.environ.get("GOFR_IQ_MCP_HOST", "localhost")
    mcp_port = _get_required_port("GOFR_IQ_MCP_PORT")
    mcpo_port = _get_required_port("GOFR_IQ_MCPO_PORT")

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
        jwt_secret = os.environ.get("GOFR_IQ_JWT_SECRET")
        vault_addr = os.environ.get("GOFR_VAULT_URL") or os.environ.get("VAULT_ADDR")
        vault_token = os.environ.get("GOFR_VAULT_TOKEN") or os.environ.get("VAULT_TOKEN")

        if not jwt_token:
            print("  Mode: Authenticated (but GOFR_IQ_JWT_TOKEN not set - will fail)")
            sys.exit(1)

        if not jwt_secret:
            print("  Mode: Authenticated (GOFR_IQ_JWT_SECRET required and must match Vault)")
            sys.exit(1)

        if not vault_addr or not vault_token:
            print("  Mode: Authenticated (VAULT_ADDR/VAULT_TOKEN required to validate JWT secret)")
            sys.exit(1)

        req = urllib.request.Request(
            f"{vault_addr}/v1/secret/data/gofr/config/jwt-signing-secret",
            headers={"X-Vault-Token": vault_token},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
        vault_jwt = payload.get("data", {}).get("data", {}).get("value")
        if not vault_jwt:
            print("  Mode: Authenticated (JWT secret missing in Vault)")
            sys.exit(1)
        if jwt_secret != vault_jwt:
            print("  Mode: Authenticated (GOFR_IQ_JWT_SECRET does not match Vault jwt-signing-secret)")
            sys.exit(1)

        print("  Mode: Authenticated (JWT token will be passed to MCP; secret validated)")
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
