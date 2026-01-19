#!/bin/bash
# GOFR-IQ Web Server Startup Script
#
# Starts the gofr-iq FastAPI web server.
#
# Usage: ./run_web.sh [--host HOST] [--port PORT] [--no-auth] [--log-level LEVEL]
#
# Options:
#   --host HOST       Host to bind to (default: 0.0.0.0)
#   --port PORT       Port to run on (default: from gofriq.env)
#   --no-auth         Disable authentication
#   --log-level LVL   Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
#   -h, --help        Show this help message
#
# REQUIREMENTS:
#   - gofriq.env must exist (run scripts/generate_envs.sh if missing)
#   - For production, use docker/start-prod.sh to start the full stack
#   - For development testing with authentication, load secrets first:
#       source lib/gofr-common/scripts/auth_env.sh --docker
#       ./scripts/run_web.sh
#
# See lib/gofr-common/scripts/readme.md for authentication guide.

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
GOFR_IQ_WEB_PORT="${GOFR_IQ_WEB_PORT}"

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
