"""GOFR-IQ MCP Server - Legacy Entry Point (Backward Compatibility).

This module maintains backward compatibility with existing scripts.
New code should use app.main_mcp instead.

Usage:
    # Deprecated - use app.main_mcp instead
    python -m app.main

    # For uvicorn compatibility
    uvicorn app.main:mcp.streamable_http_app --host 0.0.0.0 --port ${GOFR_IQ_MCP_PORT:-8080}
"""

from __future__ import annotations

import os
import sys
import warnings

# Import from new location
from app.mcp_server import create_mcp_server

# Show deprecation warning
warnings.warn(
    "app.main is deprecated. Use 'python -m app.main_mcp' instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Determine auth requirement from environment (for lazy loading)
_auth_enabled = os.environ.get("GOFR_IQ_AUTH_ENABLED", "true").lower()
_require_auth = _auth_enabled not in ("false", "0", "no")

# Create default server instance for backward compatibility
# Note: Uses environment variable to determine auth requirement
mcp = create_mcp_server(require_auth=_require_auth)


def main() -> None:
    """Run the MCP server (legacy entry point)."""
    from app.config import get_settings

    print("WARNING: Using deprecated entry point. Use 'python -m app.main_mcp' instead.")
    print()

    settings = get_settings(require_auth=_require_auth)

    print(f"Starting GOFR-IQ MCP Server on port {settings.server.mcp_port}...")
    print(f"Storage directory: {settings.storage.storage_dir}")
    print("Transport: HTTP Streamable")
    print("Press Ctrl+C to stop")

    try:
        # Use HTTP streamable transport (NOT stdio or SSE)
        mcp.run(transport="streamable-http")
    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
