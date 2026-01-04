#!/bin/bash
# GOFR-IQ Server Restart Script
# Wrapper for the shared restart_servers.sh script
# Also manages infrastructure containers (ChromaDB, Neo4j)
#
# Usage: 
#   ./restart_servers.sh --prod             # Start infra + servers (Docker containers)
#   ./restart_servers.sh --dev              # Start infra + servers (local Python, needs devcontainer)
#   ./restart_servers.sh --infra-only       # Start only infrastructure
#   ./restart_servers.sh --stop             # Stop all servers
#   ./restart_servers.sh --stop-infra       # Stop infrastructure

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

# Source centralized environment configuration
export GOFR_IQ_ENV="${GOFR_IQ_ENV:-PROD}"
if [ -f "$SCRIPT_DIR/gofriq.env" ]; then
    source "$SCRIPT_DIR/gofriq.env"
fi

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

# Parse command line arguments (these override env vars)
PASSTHROUGH_ARGS=()
INFRA_ONLY=false
NO_INFRA=false
STOP_INFRA=false
SHOW_HELP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --env)
            export GOFR_IQ_ENV="$2"
            shift 2
            ;;
        --host)
            export GOFR_IQ_HOST="$2"
            shift 2
            ;;
        --mcp-port)
            export GOFR_IQ_MCP_PORT="$2"
            shift 2
            ;;
        --mcpo-port)
            export GOFR_IQ_MCPO_PORT="$2"
            shift 2
            ;;
        --web-port)
            export GOFR_IQ_WEB_PORT="$2"
            shift 2
            ;;
        --infra-only|--infra)
            INFRA_ONLY=true
            shift
            ;;
        --no-infra|--servers-only)
            NO_INFRA=true
            shift
            ;;
        --stop-infra)
            STOP_INFRA=true
            shift
            ;;
        --prod|--docker|--dev|--local|--kill-all|--stop)
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
    echo "Usage: $0 <mode> [options]"
    echo ""
    echo "MODE (required):"
    echo "  --prod, --docker      Run servers as Docker containers (works from host)"
    echo "  --dev, --local        Run servers as local Python (requires devcontainer)"
    echo ""
    echo "INFRASTRUCTURE OPTIONS:"
    echo "  --infra-only          Only start infrastructure (ChromaDB, Neo4j)"
    echo "  --no-infra            Skip infrastructure, only start servers"
    echo "  --stop-infra          Stop infrastructure containers"
    echo ""
    echo "SERVER OPTIONS:"
    echo "  --stop, --kill-all    Stop all running servers"
    echo "  --env PROD|TEST       Set environment mode (default: PROD)"
    echo "  --host HOST           Set server host"
    echo "  --mcp-port PORT       Set MCP server port"
    echo "  --mcpo-port PORT      Set MCPO proxy port"
    echo "  --web-port PORT       Set web server port"
    echo ""
    echo "EXAMPLES:"
    echo "  $0 --prod             Start everything with Docker containers"
    echo "  $0 --dev              Start everything with local Python"
    echo "  $0 --infra-only       Only start ChromaDB and Neo4j"
    echo "  $0 --prod --no-infra  Only start server containers (infra already running)"
    echo "  $0 --stop             Stop all servers"
    echo "  $0 --stop-infra       Stop infrastructure containers"
    exit 0
fi

# Handle stop infrastructure
if [ "$STOP_INFRA" = true ]; then
    stop_infra
    exit 0
fi

# Re-source gofriq.env after command-line args may have changed GOFR_IQ_ENV
if [ -f "$SCRIPT_DIR/gofriq.env" ]; then
    source "$SCRIPT_DIR/gofriq.env"
fi

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
export GOFR_PROJECT_ROOT="$GOFR_IQ_ROOT"
export GOFR_LOGS_DIR="$GOFR_IQ_LOGS"
export GOFR_DATA_DIR="$GOFR_IQ_DATA"
export GOFR_ENV="$GOFR_IQ_ENV"
export GOFR_MCP_PORT="$GOFR_IQ_MCP_PORT"
export GOFR_MCPO_PORT="$GOFR_IQ_MCPO_PORT"
export GOFR_WEB_PORT="$GOFR_IQ_WEB_PORT"
export GOFR_MCP_HOST="$GOFR_IQ_HOST"
export GOFR_MCPO_HOST="$GOFR_IQ_HOST"
export GOFR_WEB_HOST="$GOFR_IQ_HOST"
export GOFR_NETWORK="$GOFR_IQ_DOCKER_NETWORK"
export GOFR_DOCKER_DIR="$DOCKER_DIR"

# Extra args for MCP server (project-specific)
# GOFR-IQ doesn't need web-url arg
export GOFR_MCP_EXTRA_ARGS=""

# Extra args for Web server - disable auth for development
export GOFR_WEB_EXTRA_ARGS="--no-auth"

# Export port configuration for docker-compose
export GOFR_IQ_MCP_PORT GOFR_IQ_MCPO_PORT GOFR_IQ_WEB_PORT

# Call shared script
source "$COMMON_SCRIPTS/restart_servers.sh" "${PASSTHROUGH_ARGS[@]}"
