#!/bin/bash
# gofr-iq MCP Server Startup Script
# Starts the MCP server with proper authentication and configuration.

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Locate project root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Source centralized environment configuration
if [ -f "${SCRIPT_DIR}/gofriq.env" ]; then
    source "${SCRIPT_DIR}/gofriq.env"
fi

# Configuration with environment variable fallbacks
HOST="${GOFR_IQ_MCP_HOST:-${GOFR_IQ_HOST:-0.0.0.0}}"
PORT="${GOFR_IQ_MCP_PORT}"
NO_AUTH="${GOFR_IQ_NO_AUTH:-false}"
LOG_LEVEL="${GOFR_IQ_LOG_LEVEL:-INFO}"
STORAGE_DIR="${GOFR_IQ_STORAGE_DIR:-${GOFR_IQ_STORAGE}}"

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --storage-dir)
            STORAGE_DIR="$2"
            shift 2
            ;;
        --no-auth)
            NO_AUTH="true"
            shift
            ;;
        --log-level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --host HOST           Host to bind to (default: 0.0.0.0)"
            echo "  --port PORT           Port to run MCP server on (default: from gofriq.env)"
            echo "  --storage-dir DIR     Storage directory for documents"
            echo "  --no-auth             Disable authentication"
            echo "  --log-level LEVEL     Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
            echo "  -h, --help            Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  GOFR_IQ_MCP_HOST         Default host (default: 0.0.0.0)"
            echo "  GOFR_IQ_MCP_PORT         Default port (from gofriq.env)"
            echo "  GOFR_IQ_STORAGE_DIR      Storage directory"
            echo "  GOFR_IQ_NO_AUTH          Set to 'true' to disable auth"
            echo "  GOFR_IQ_LOG_LEVEL        Logging level (default: INFO)"
            echo "  GOFR_JWT_SECRET          JWT secret for authentication (shared)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate authentication configuration
if [ "$NO_AUTH" = "false" ] && [ -z "${GOFR_JWT_SECRET:-}" ]; then
    echo -e "${YELLOW}WARNING: No JWT secret configured and authentication is enabled${NC}"
    echo -e "${YELLOW}Set GOFR_JWT_SECRET environment variable or use --no-auth${NC}"
fi

# Build command line arguments
CMD_ARGS=(
    "--host" "$HOST"
    "--port" "$PORT"
    "--log-level" "$LOG_LEVEL"
)

if [ "$NO_AUTH" = "true" ]; then
    CMD_ARGS+=("--no-auth")
fi

if [ -n "$STORAGE_DIR" ]; then
    CMD_ARGS+=("--storage-dir" "$STORAGE_DIR")
fi

# Display startup information
echo "======================================================================="
echo "GOFR-IQ MCP Server"
echo "======================================================================="
echo "Host:         $HOST"
echo "Port:         $PORT"
echo "Storage:      ${STORAGE_DIR:-<from config>}"
echo "Auth:         $([ "$NO_AUTH" = "true" ] && echo "Disabled" || echo "Enabled")"
echo "Log Level:    $LOG_LEVEL"
echo "======================================================================="
echo ""

# Start the server
echo -e "${GREEN}Starting MCP server...${NC}"
uv run python -m app.main_mcp "${CMD_ARGS[@]}"
