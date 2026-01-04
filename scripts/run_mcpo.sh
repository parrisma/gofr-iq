#!/bin/bash
# Start GOFR-IQ MCPO wrapper server
# Exposes MCP server as OpenAPI/REST endpoints

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

# Source environment configuration if available
if [ -f "${SCRIPT_DIR}/gofriq.env" ]; then
    source "${SCRIPT_DIR}/gofriq.env"
fi

# Set defaults
export GOFR_IQ_MCP_HOST="${GOFR_IQ_MCP_HOST:-localhost}"
export GOFR_IQ_MCP_PORT="${GOFR_IQ_MCP_PORT}"
export GOFR_IQ_MCPO_PORT="${GOFR_IQ_MCPO_PORT}"

echo "=== Starting GOFR-IQ MCPO Wrapper ==="
echo "MCP Server: http://${GOFR_IQ_MCP_HOST}:${GOFR_IQ_MCP_PORT}/mcp"
echo "MCPO Proxy: http://localhost:${GOFR_IQ_MCPO_PORT}"
echo ""

# Run with uv
uv run python -m app.main_mcpo "$@"
