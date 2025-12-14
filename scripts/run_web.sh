#!/bin/bash
# GOFR-IQ Web Server Startup Script
#
# Starts the gofr-iq FastAPI web server.
#
# Usage: ./run_web.sh [--host HOST] [--port PORT] [--no-auth] [--log-level LEVEL]

set -euo pipefail

# Locate script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source environment configuration
source "${SCRIPT_DIR}/gofriq.env"

# Change to project root
cd "${PROJECT_ROOT}"

# Parse command line arguments
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --host)
            GOFR_IQ_HOST="$2"
            shift 2
            ;;
        --port)
            GOFR_IQ_WEB_PORT="$2"
            shift 2
            ;;
        --no-auth)
            EXTRA_ARGS+=("--no-auth")
            shift
            ;;
        --log-level)
            EXTRA_ARGS+=("--log-level" "$2")
            shift 2
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# Defaults
GOFR_IQ_HOST="${GOFR_IQ_HOST:-0.0.0.0}"
# Source gofriq.env for canonical port definitions
if [ -f "${SCRIPT_DIR}/gofriq.env" ]; then
    source "${SCRIPT_DIR}/gofriq.env"
fi

GOFR_IQ_WEB_PORT="${GOFR_IQ_WEB_PORT:-${GOFR_IQ_WEB_PORT}}"

# Export for Python process
export GOFR_IQ_HOST
export GOFR_IQ_WEB_PORT

echo "======================================================================="
echo "  Starting GOFR-IQ Web Server"
echo "======================================================================="
echo "Host: $GOFR_IQ_HOST"
echo "Port: $GOFR_IQ_WEB_PORT"
echo "======================================================================="

# Run with uv
exec uv run python -m app.main_web \
    --host "$GOFR_IQ_HOST" \
    --port "$GOFR_IQ_WEB_PORT" \
    "${EXTRA_ARGS[@]}"
