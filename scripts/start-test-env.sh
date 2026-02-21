#!/bin/bash
# Helper for managing the GOFR-IQ test infrastructure stack (Vault, ChromaDB, Neo4j).
# Delegates to docker/manage-infra.sh and handles dev-container network hookup
# plus lightweight service verification so other scripts (run_tests.sh, CI jobs)
# can stay small.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANAGE_INFRA="${PROJECT_ROOT}/docker/manage-infra.sh"
DEV_CONTAINER="${DEV_CONTAINER:-gofr-iq-dev}"
NETWORK_NAME="${TEST_NETWORK:-gofr-test-net}"

# Default service endpoints for verification (can be overridden via env vars)
# Prefer GOFR_IQ_* (Option A), but keep fallback to legacy GOFR_* during migration.
VAULT_URL="${GOFR_IQ_VAULT_URL:-${GOFR_VAULT_URL:-http://gofr-iq-vault-test:8200}}"
CHROMA_HOST="${GOFR_IQ_CHROMADB_HOST:-gofr-iq-chromadb-test}"
CHROMA_PORT="${GOFR_IQ_CHROMADB_PORT:-8000}"
NEO4J_HOST="${GOFR_IQ_NEO4J_HOST:-gofr-iq-neo4j-test}"
NEO4J_HTTP_PORT_HOST="${GOFR_NEO4J_HTTP_PORT:-7474}"
NEO4J_HTTP_PORT_CONTAINER="${GOFR_NEO4J_HTTP_PORT_CONTAINER:-7474}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $(basename "$0") <start|stop|status|verify> [options]

Commands:
  start [--rebuild]     Start the test infra stack (optionally rebuild images)
  stop                  Stop the test infra stack
  status                Show docker status for test infra
  verify                Check health of Vault/ChromaDB/Neo4j endpoints
EOF
}

require_manage_script() {
    if [ ! -f "$MANAGE_INFRA" ]; then
        echo -e "${RED}manage-infra.sh not found at ${MANAGE_INFRA}${NC}" >&2
        exit 1
    fi
}

maybe_connect_dev_container() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${DEV_CONTAINER}$"; then
        return 0
    fi
    if docker network inspect "$NETWORK_NAME" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | grep -q "${DEV_CONTAINER}"; then
        return 0
    fi
    echo -e "${YELLOW}Connecting ${DEV_CONTAINER} to ${NETWORK_NAME}...${NC}"
    docker network connect "$NETWORK_NAME" "$DEV_CONTAINER" 2>/dev/null || true
}

verify_services() {
    local ok=true
    echo -e "${BLUE}Verifying test services...${NC}"

    echo -n "  Vault (${VAULT_URL})... "
    if curl -s --max-time 5 "${VAULT_URL}/v1/sys/health" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"; ok=false
    fi

    local chroma_url="http://${CHROMA_HOST}:${CHROMA_PORT}"
    echo -n "  ChromaDB (${chroma_url})... "
    if curl -s --max-time 5 "${chroma_url}/api/v1/heartbeat" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"; ok=false
    fi

    local neo4j_url="http://${NEO4J_HOST}:${NEO4J_HTTP_PORT_CONTAINER}"
    echo -n "  Neo4j (${neo4j_url})... "
    if curl -s --max-time 5 "${neo4j_url}" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        # Fallback to host-exposed port in case we're running outside the test network
        local neo4j_host_url="http://localhost:${NEO4J_HTTP_PORT_HOST}"
        if curl -s --max-time 5 "${neo4j_host_url}" >/dev/null 2>&1; then
            echo -e "${YELLOW}!${NC} (reachable via ${neo4j_host_url})"
        else
            echo -e "${RED}✗${NC}"; ok=false
        fi
    fi

    if [ "$ok" = true ]; then
        echo -e "${GREEN}All services reachable${NC}"
        return 0
    fi

    echo -e "${RED}One or more services are unavailable${NC}" >&2
    echo -e "${YELLOW}Hint: ensure the dev container is attached to ${NETWORK_NAME}${NC}"
    return 1
}

run_builds_if_needed() {
    local rebuild="$1"
    if [ "$rebuild" != true ]; then
        return 0
    fi
    echo -e "${YELLOW}Rebuilding Docker images for test infra...${NC}"
    for script in build-chromadb.sh build-neo4j.sh build-prod.sh; do
        local path="${PROJECT_ROOT}/docker/${script}"
        if [ -f "$path" ]; then
            bash "$path"
        else
            echo -e "${YELLOW}Skipping missing ${path}${NC}"
        fi
    done
    echo -e "${GREEN}Docker images rebuilt${NC}"
}

cmd_start() {
    local rebuild=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --rebuild)
                rebuild=true
                shift
                ;;
            *)
                echo -e "${RED}Unknown option for start: $1${NC}" >&2
                usage
                exit 1
                ;;
        esac
    done

    require_manage_script
    run_builds_if_needed "$rebuild"

    echo -e "${GREEN}Starting GOFR-IQ test infrastructure...${NC}"
    bash "$MANAGE_INFRA" start --test
    maybe_connect_dev_container
    verify_services
}

cmd_stop() {
    require_manage_script
    echo -e "${YELLOW}Stopping GOFR-IQ test infrastructure...${NC}"
    bash "$MANAGE_INFRA" stop --test
}

cmd_status() {
    require_manage_script
    bash "$MANAGE_INFRA" status --test
}

command="${1:-}"
if [ -z "$command" ]; then
    usage
    exit 1
fi
shift || true

case "$command" in
    start)
        cmd_start "$@"
        ;;
    stop)
        cmd_stop "$@"
        ;;
    status)
        cmd_status "$@"
        ;;
    verify)
        verify_services "$@"
        ;;
    *)
        usage
        exit 1
        ;;
esac
