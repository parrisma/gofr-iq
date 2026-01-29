#!/bin/bash
# GOFR-IQ Server Management Script
# Simple wrapper around docker compose
#
# Usage:
#   ./manage_servers.sh start       # Start all services
#   ./manage_servers.sh stop        # Stop all services
#   ./manage_servers.sh restart     # Restart all services
#   ./manage_servers.sh status      # Show service status
#   ./manage_servers.sh logs [svc]  # Tail logs (optionally for specific service)
#
# For first-time setup, use scripts/start-prod.sh instead.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCKER_DIR="${PROJECT_ROOT}/docker"
COMPOSE_FILE="${DOCKER_DIR}/docker-compose.yml"

# Source environment configuration
if [ -f "${SCRIPT_DIR}/gofriq.env" ]; then
    source "${SCRIPT_DIR}/gofriq.env"
fi

# Source port configuration
if [ -f "${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env" ]; then
    set -a
    source "${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
    set +a
fi

# Set defaults for secrets (suppresses docker compose warnings)
# Real values are loaded from Vault by start-prod.sh
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-placeholder}"
export GOFR_IQ_JWT_SECRET="${GOFR_IQ_JWT_SECRET:-placeholder}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    echo "GOFR-IQ Server Management"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  start           Start all services (infra + app)"
    echo "  stop            Stop all services"
    echo "  restart         Restart all services"
    echo "  status          Show service status"
    echo "  logs [service]  Tail logs (mcp, mcpo, web, neo4j, chromadb)"
    echo ""
    echo "Examples:"
    echo "  $0 start        # Start everything"
    echo "  $0 stop         # Stop everything"
    echo "  $0 logs mcp     # Tail MCP server logs"
    echo "  $0 status       # Show container status"
    echo ""
    echo "Note: For first-time setup, use scripts/start-prod.sh"
}

cmd_start() {
    echo -e "${GREEN}Starting gofr-iq services...${NC}"
    docker compose -f "$COMPOSE_FILE" up -d
    echo -e "${GREEN}Services started. Use '$0 status' to check health.${NC}"
}

cmd_stop() {
    echo -e "${YELLOW}Stopping gofr-iq services...${NC}"
    docker compose -f "$COMPOSE_FILE" stop
    echo -e "${GREEN}Services stopped.${NC}"
}

cmd_restart() {
    echo -e "${YELLOW}Restarting gofr-iq services...${NC}"
    docker compose -f "$COMPOSE_FILE" restart
    echo -e "${GREEN}Services restarted.${NC}"
}

cmd_status() {
    echo -e "${GREEN}Service Status:${NC}"
    docker compose -f "$COMPOSE_FILE" ps
}

cmd_logs() {
    local service="$1"
    if [ -n "$service" ]; then
        docker compose -f "$COMPOSE_FILE" logs -f "$service"
    else
        docker compose -f "$COMPOSE_FILE" logs -f
    fi
}

# Main
case "${1:-}" in
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs "$2"
        ;;
    -h|--help|help|"")
        usage
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        usage
        exit 1
        ;;
esac
