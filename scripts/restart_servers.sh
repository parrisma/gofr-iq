#!/bin/bash
# GOFR-IQ Server Restart Script
# Wrapper for the shared restart_servers.sh script
#
# Usage: ./restart_servers.sh [--kill-all] [--env PROD|TEST] [--host HOST] 
#        [--mcp-port PORT] [--mcpo-port PORT] [--web-port PORT]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SCRIPTS="$SCRIPT_DIR/../../gofr-common/scripts"

# Check for lib/gofr-common location first (inside container)
if [ -d "$SCRIPT_DIR/../lib/gofr-common/scripts" ]; then
    COMMON_SCRIPTS="$SCRIPT_DIR/../lib/gofr-common/scripts"
fi

# Source centralized configuration (defaults to PROD for restart script)
export GOFRIQ_ENV="${GOFRIQ_ENV:-PROD}"
source "$SCRIPT_DIR/gofriq.env"

# Parse command line arguments (these override env vars)
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --env)
            export GOFRIQ_ENV="$2"
            shift 2
            ;;
        --host)
            export GOFRIQ_HOST="$2"
            shift 2
            ;;
        --mcp-port)
            export GOFRIQ_MCP_PORT="$2"
            shift 2
            ;;
        --mcpo-port)
            export GOFRIQ_MCPO_PORT="$2"
            shift 2
            ;;
        --web-port)
            export GOFRIQ_WEB_PORT="$2"
            shift 2
            ;;
        --kill-all|--help)
            # Pass through to common script
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--kill-all] [--env PROD|TEST] [--host HOST] [--mcp-port PORT] [--mcpo-port PORT] [--web-port PORT]"
            exit 1
            ;;
    esac
done

# Re-source after env vars may have changed
source "$SCRIPT_DIR/gofriq.env"

# Map project-specific vars to common vars
export GOFR_PROJECT_NAME="gofr-iq"
export GOFR_PROJECT_ROOT="$GOFRIQ_ROOT"
export GOFR_LOGS_DIR="$GOFRIQ_LOGS"
export GOFR_DATA_DIR="$GOFRIQ_DATA"
export GOFR_ENV="$GOFRIQ_ENV"
export GOFR_MCP_PORT="$GOFRIQ_MCP_PORT"
export GOFR_MCPO_PORT="$GOFRIQ_MCPO_PORT"
export GOFR_WEB_PORT="$GOFRIQ_WEB_PORT"
export GOFR_MCP_HOST="$GOFRIQ_HOST"
export GOFR_MCPO_HOST="$GOFRIQ_HOST"
export GOFR_WEB_HOST="$GOFRIQ_HOST"
export GOFR_NETWORK="$GOFRIQ_DOCKER_NETWORK"

# Extra args for MCP server (project-specific)
export GOFR_MCP_EXTRA_ARGS="--web-url http://$GOFRIQ_HOST:$GOFRIQ_WEB_PORT"

# Call shared script
source "$COMMON_SCRIPTS/restart_servers.sh" "${PASSTHROUGH_ARGS[@]}"
