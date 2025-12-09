#!/bin/bash
# GOFR-IQ Server Restart Script
# Wrapper for the shared restart_servers.sh script
# Also manages infrastructure containers (ChromaDB, Neo4j)
#
# Usage: ./restart_servers.sh [--kill-all] [--env PROD|TEST] [--host HOST] 
#        [--mcp-port PORT] [--mcpo-port PORT] [--web-port PORT]
#        [--infra-only] [--no-infra] [--stop-infra]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCKER_DIR="${PROJECT_ROOT}/docker"
COMMON_SCRIPTS="$SCRIPT_DIR/../../gofr-common/scripts"

# Check for lib/gofr-common location first (inside container)
if [ -d "$SCRIPT_DIR/../lib/gofr-common/scripts" ]; then
    COMMON_SCRIPTS="$SCRIPT_DIR/../lib/gofr-common/scripts"
fi

# Source centralized configuration (defaults to PROD for restart script)
export GOFRIQ_ENV="${GOFRIQ_ENV:-PROD}"
source "$SCRIPT_DIR/gofriq.env"

# Infrastructure management functions
start_infra() {
    echo -e "${BLUE}Starting infrastructure containers...${NC}"
    
    if ! command -v docker &> /dev/null; then
        echo -e "${YELLOW}Docker not available. Skipping infrastructure.${NC}"
        return 0
    fi
    
    cd "${DOCKER_DIR}"
    docker compose -f docker-compose.yml up -d chromadb neo4j
    
    # Wait for health
    echo -e "${YELLOW}Waiting for services to be healthy...${NC}"
    local max_wait=120
    local elapsed=0
    
    while [ $elapsed -lt $max_wait ]; do
        local chroma_health=$(docker inspect --format='{{.State.Health.Status}}' gofr-iq-chromadb 2>/dev/null || echo "starting")
        local neo4j_health=$(docker inspect --format='{{.State.Health.Status}}' gofr-iq-neo4j 2>/dev/null || echo "starting")
        
        if [ "$chroma_health" = "healthy" ] && [ "$neo4j_health" = "healthy" ]; then
            echo -e "${GREEN}Infrastructure is ready${NC}"
            cd "${PROJECT_ROOT}"
            return 0
        fi
        
        sleep 2
        elapsed=$((elapsed + 2))
        printf "."
    done
    
    echo -e "\n${RED}Infrastructure did not become healthy in ${max_wait}s${NC}"
    docker compose -f docker-compose.yml logs chromadb neo4j
    cd "${PROJECT_ROOT}"
    return 1
}

stop_infra() {
    echo -e "${YELLOW}Stopping infrastructure containers...${NC}"
    
    if command -v docker &> /dev/null; then
        cd "${DOCKER_DIR}"
        docker compose -f docker-compose.yml stop chromadb neo4j 2>/dev/null || true
        cd "${PROJECT_ROOT}"
    fi
    
    echo -e "${GREEN}Infrastructure stopped${NC}"
}

infra_status() {
    echo -e "${BLUE}Infrastructure status:${NC}"
    
    if ! command -v docker &> /dev/null; then
        echo "Docker not available"
        return
    fi
    
    cd "${DOCKER_DIR}"
    docker compose -f docker-compose.yml ps chromadb neo4j 2>/dev/null || echo "No containers running"
    cd "${PROJECT_ROOT}"
}

# Parse command line arguments (these override env vars)
PASSTHROUGH_ARGS=()
INFRA_ONLY=false
NO_INFRA=false
STOP_INFRA=false
SHOW_HELP=false

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
        --infra-only)
            INFRA_ONLY=true
            shift
            ;;
        --no-infra)
            NO_INFRA=true
            shift
            ;;
        --stop-infra)
            STOP_INFRA=true
            shift
            ;;
        --kill-all)
            # Pass through to common script
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
        --help|-h)
            SHOW_HELP=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            SHOW_HELP=true
            break
            ;;
    esac
done

if [ "$SHOW_HELP" = true ]; then
    echo "GOFR-IQ Server Restart Script"
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Server Options:"
    echo "  --kill-all            Kill all running servers"
    echo "  --env PROD|TEST       Set environment mode (default: PROD)"
    echo "  --host HOST           Set server host"
    echo "  --mcp-port PORT       Set MCP server port"
    echo "  --mcpo-port PORT      Set MCPO proxy port"
    echo "  --web-port PORT       Set web server port"
    echo ""
    echo "Infrastructure Options:"
    echo "  --infra-only          Only start infrastructure (ChromaDB, Neo4j)"
    echo "  --no-infra            Skip infrastructure, only restart servers"
    echo "  --stop-infra          Stop infrastructure containers"
    echo ""
    echo "Examples:"
    echo "  $0                    Start infra + servers"
    echo "  $0 --infra-only       Only start ChromaDB and Neo4j"
    echo "  $0 --no-infra         Only restart MCP/Web servers"
    echo "  $0 --stop-infra       Stop infrastructure containers"
    echo "  $0 --kill-all         Kill all servers and stop infra"
    exit 0
fi

# Handle stop infrastructure
if [ "$STOP_INFRA" = true ]; then
    stop_infra
    exit 0
fi

# Re-source after env vars may have changed
source "$SCRIPT_DIR/gofriq.env"

# Start infrastructure if not disabled
if [ "$NO_INFRA" = false ]; then
    start_infra
fi

# Exit if only infrastructure was requested
if [ "$INFRA_ONLY" = true ]; then
    infra_status
    exit 0
fi

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
