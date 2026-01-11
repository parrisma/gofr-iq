#!/bin/bash
# =============================================================================
# GOFR-IQ Test Runner
# =============================================================================
# Standardized test runner script with consistent configuration across all
# GOFR projects. This script:
# - Sets up virtual environment and PYTHONPATH
# - Configures test ports for MCP and Web servers
# - Supports coverage reporting
# - Supports Docker execution
# - Supports test categories (unit, integration, all)
# - Manages server lifecycle for integration tests
# - Supports optional ChromaDB/Neo4j infrastructure
#
# Usage:
#   ./scripts/run_tests.sh                          # Run all tests
#   ./scripts/run_tests.sh test/mcp/                # Run specific test directory
#   ./scripts/run_tests.sh -k "iq"                  # Run tests matching keyword
#   ./scripts/run_tests.sh -v                       # Run with verbose output
#   ./scripts/run_tests.sh --coverage               # Run with coverage report
#   ./scripts/run_tests.sh --coverage-html          # Run with HTML coverage report
#   ./scripts/run_tests.sh --docker                 # Run tests in Docker container
#   ./scripts/run_tests.sh --unit                   # Run unit tests only (no servers)
#   ./scripts/run_tests.sh --integration            # Run integration tests (with servers)
#   ./scripts/run_tests.sh --no-servers             # Run without starting servers
#   ./scripts/run_tests.sh --rebuild                # Rebuild Docker images before starting
#   ./scripts/run_tests.sh --stop                   # Stop servers only
#   ./scripts/run_tests.sh --cleanup-only           # Clean environment only
# =============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# =============================================================================
# CONFIGURATION
# =============================================================================

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project-specific configuration
PROJECT_NAME="gofr-iq"
ENV_PREFIX="GOFR_IQ"
CONTAINER_NAME="gofr-iq-dev"
TEST_DIR="test"
COVERAGE_SOURCE="app"
LOG_DIR="${PROJECT_ROOT}/logs"

# Activate virtual environment
VENV_DIR="${PROJECT_ROOT}/.venv"
if [ -f "${VENV_DIR}/bin/activate" ]; then
    source "${VENV_DIR}/bin/activate"
    echo "Activated venv: ${VENV_DIR}"
else
    echo -e "${YELLOW}Warning: Virtual environment not found at ${VENV_DIR}${NC}"
fi

# Purge test data from previous runs
echo "Purging test data..."
"${SCRIPT_DIR}/purge_local_data.sh" --test-only --force

# =============================================================================
# TEST CONFIGURATION
# =============================================================================
# IMPORTANT: Configuration loaded from .env files (single source of truth)
# - Ports: GOFR_IQ_*_PORT loaded from gofr_ports.env
# - Secrets: GOFR_JWT_SECRET, GOFR_VAULT_DEV_TOKEN from .env
# =============================================================================
export GOFR_IQ_ENV="TEST"

# Clear stale tokens from previous sessions (they may have wrong JWT signature)
# This ensures tests create fresh tokens with the correct secret
unset GOFR_IQ_ADMIN_TOKEN GOFR_IQ_PUBLIC_TOKEN 2>/dev/null || true

# Load centralized port configuration from gofr-common .env file
GOFR_PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
if [ -f "${GOFR_PORTS_FILE}" ]; then
    echo "Loading port configuration from gofr_ports.env"
    set -a
    source "${GOFR_PORTS_FILE}"
    set +a
    
    # Apply test port offsets (prod ports + 100)
    # GOFR-IQ Service Ports
    export GOFR_IQ_MCP_PORT="${GOFR_IQ_MCP_PORT_TEST:-$((GOFR_IQ_MCP_PORT + 100))}"
    export GOFR_IQ_MCPO_PORT="${GOFR_IQ_MCPO_PORT_TEST:-$((GOFR_IQ_MCPO_PORT + 100))}"
    export GOFR_IQ_WEB_PORT="${GOFR_IQ_WEB_PORT_TEST:-$((GOFR_IQ_WEB_PORT + 100))}"
    
    # Infrastructure Ports
    export GOFR_VAULT_PORT="${GOFR_VAULT_PORT_TEST:-$((GOFR_VAULT_PORT + 100))}"
    export GOFR_CHROMA_PORT="${GOFR_CHROMA_PORT_TEST:-$((GOFR_CHROMA_PORT + 100))}"
    export GOFR_NEO4J_HTTP_PORT="${GOFR_NEO4J_HTTP_PORT_TEST:-$((GOFR_NEO4J_HTTP_PORT + 100))}"
    export GOFR_NEO4J_BOLT_PORT="${GOFR_NEO4J_BOLT_PORT_TEST:-$((GOFR_NEO4J_BOLT_PORT + 100))}"
    
    echo "  Port configuration loaded (test mode with +100 offset)"
else
    echo -e "${RED}ERROR: Port configuration file not found: ${GOFR_PORTS_FILE}${NC}" >&2
    exit 1
fi

# Load secrets from gofr-common .env if available
GOFR_COMMON_ENV="${PROJECT_ROOT}/lib/gofr-common/.env"
if [ -f "${GOFR_COMMON_ENV}" ]; then
    set -a
    source "${GOFR_COMMON_ENV}"
    set +a
    echo "Loaded secrets from gofr-common/.env"
fi

# JWT Secret: Required for auth - should come from .env
if [ -z "${GOFR_JWT_SECRET:-}" ]; then
    echo -e "${YELLOW}Warning: GOFR_JWT_SECRET not set, generating test secret${NC}"
    export GOFR_JWT_SECRET="test-jwt-secret-$(date +%s)"
fi
echo "  JWT Secret: ${GOFR_JWT_SECRET:0:20}..."

# Vault Token: Required for vault auth backend
if [ -z "${GOFR_VAULT_DEV_TOKEN:-}" ]; then
    echo -e "${YELLOW}Warning: GOFR_VAULT_DEV_TOKEN not set, using default${NC}"
    export GOFR_VAULT_DEV_TOKEN="gofr-dev-root-token"
fi

# Auth Backend Configuration - Vault for shared state between tests and servers
# Tests run INSIDE dev container connected to gofr-test-net, use container hostnames
export GOFR_AUTH_BACKEND="vault"
export GOFR_VAULT_URL="http://gofr-vault-test:8200"
export GOFR_VAULT_TOKEN="${GOFR_VAULT_DEV_TOKEN}"
export GOFR_VAULT_PATH_PREFIX="gofr-test/auth"
export GOFR_VAULT_MOUNT_POINT="secret"

# Source centralized environment configuration (won't override already-set vars)
if [ -f "${SCRIPT_DIR}/gofr-iq.env" ]; then
    source "${SCRIPT_DIR}/gofr-iq.env"
elif [ -f "${SCRIPT_DIR}/gofriq.env" ]; then
    # Legacy support
    source "${SCRIPT_DIR}/gofriq.env"
fi

# Set up PYTHONPATH for gofr-common discovery
if [ -d "${PROJECT_ROOT}/lib/gofr-common/src" ]; then
    export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/lib/gofr-common/src:${PYTHONPATH:-}"
elif [ -d "${PROJECT_ROOT}/../gofr-common/src" ]; then
    export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/../gofr-common/src:${PYTHONPATH:-}"
else
    export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
fi

# Infrastructure (ChromaDB, Neo4j) - for tests connecting to external services
# Tests run INSIDE dev container connected to gofr-test-net, use container hostnames
# Ports are internal container ports (8000 for chroma, 7687 for neo4j bolt)
export GOFR_IQ_CHROMADB_HOST="gofr-iq-chromadb-test"
export GOFR_IQ_CHROMADB_PORT="8000"
export GOFR_IQ_NEO4J_HOST="gofr-iq-neo4j-test"
export GOFR_IQ_NEO4J_BOLT_PORT="7687"
export GOFR_IQ_NEO4J_URI="bolt://gofr-iq-neo4j-test:7687"
export GOFR_IQ_NEO4J_PASSWORD="${GOFR_IQ_NEO4J_PASSWORD:-testpassword}"

# JWT Secret: Use GOFR_JWT_SECRET from gofr_ports.sh as THE single source of truth
# Legacy alias for backward compatibility with code that uses GOFR_IQ_JWT_SECRET
export GOFR_IQ_JWT_SECRET="${GOFR_JWT_SECRET}"
export GOFR_IQ_MCP_PORT="${GOFR_IQ_MCP_PORT}"
export GOFR_IQ_WEB_PORT="${GOFR_IQ_WEB_PORT}"

# Ensure directories exist
mkdir -p "${LOG_DIR}"
mkdir -p "${GOFR_IQ_STORAGE:-${PROJECT_ROOT}/data/storage}"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

print_header() {
    echo -e "${GREEN}=== ${PROJECT_NAME} Test Runner ===${NC}"
    echo "Project root: ${PROJECT_ROOT}"
    echo "Environment: ${GOFR_IQ_ENV}"
    echo "JWT Secret: ${GOFR_IQ_JWT_SECRET:0:20}..."
    echo "Auth Backend: ${GOFR_AUTH_BACKEND}"
    echo "Vault URL: ${GOFR_VAULT_URL}"
    echo "MCP Port: ${GOFR_IQ_MCP_PORT} (test port, internal)"
    echo "MCPO Port: ${GOFR_IQ_MCPO_PORT} (test port, internal)"
    echo "Web Port: ${GOFR_IQ_WEB_PORT} (test port, internal)"
    echo "ChromaDB: ${GOFR_IQ_CHROMADB_HOST}:${GOFR_IQ_CHROMADB_PORT} (container)"
    echo "Neo4j: ${GOFR_IQ_NEO4J_HOST}:${GOFR_IQ_NEO4J_BOLT_PORT} (container)"
    echo ""
}

port_in_use() {
    local port=$1
    if command -v lsof >/dev/null 2>&1; then
        lsof -i ":${port}" >/dev/null 2>&1
    elif command -v ss >/dev/null 2>&1; then
        ss -tuln | grep -q ":${port} "
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tuln | grep -q ":${port} "
    else
        timeout 1 bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/${port}" >/dev/null 2>&1
    fi
}

free_port() {
    local port=$1
    if ! port_in_use "$port"; then
        return 0
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti ":${port}" | xargs -r kill -9 2>/dev/null || true
    elif command -v ss >/dev/null 2>&1; then
        ss -lptn "sport = :${port}" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d'=' -f2 | xargs -r kill -9 2>/dev/null || true
    fi
    sleep 1
}

stop_servers() {
    echo "Stopping server processes..."
    
    # Use specific patterns with full path to avoid killing unrelated processes
    # This prevents accidentally killing the terminal or VS Code processes
    local pids=""
    
    # Find PIDs for our specific server processes
    pids=$(pgrep -f "app/main_mcp\.py" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Stopping MCP server (PIDs: $pids)"
        echo "$pids" | xargs -r kill -9 2>/dev/null || true
    fi
    
    pids=$(pgrep -f "app/main_web\.py" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Stopping Web server (PIDs: $pids)"
        echo "$pids" | xargs -r kill -9 2>/dev/null || true
    fi
    
    pids=$(pgrep -f "app/main_mcpo\.py" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Stopping MCPO server (PIDs: $pids)"
        echo "$pids" | xargs -r kill -9 2>/dev/null || true
    fi
    
    # Also stop mcpo wrapper if running
    pids=$(pgrep -f "mcpo.*--port.*${GOFR_IQ_MCPO_PORT}" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "Stopping MCPO wrapper (PIDs: $pids)"
        echo "$pids" | xargs -r kill -9 2>/dev/null || true
    fi
    
    sleep 1
    
    # Verify cleanup
    if pgrep -f "app/main_(mcp|web|mcpo)\.py" >/dev/null 2>&1; then
        echo -e "${YELLOW}WARNING: Some server processes may still be running${NC}"
        pgrep -af "app/main_(mcp|web|mcpo)\.py" 2>/dev/null || true
        return 1
    fi
    echo "All server processes stopped"
    return 0
}

start_chromadb() {
    echo -e "${YELLOW}Starting ChromaDB container...${NC}"
    
    # Check if container already running
    if docker ps --format '{{.Names}}' | grep -q "^gofr-iq-chromadb$"; then
        echo -e "${GREEN}ChromaDB container already running${NC}"
        return 0
    fi
    
    # Start container directly without waiting in the script
    # (the script will fail to connect to localhost from inside dev container)
    docker run -d \
        --name gofr-iq-chromadb \
        --network gofr-net \
        -p "${GOFR_IQ_CHROMADB_PORT}:8000" \
        gofr-iq-chromadb:latest >/dev/null 2>&1 || {
        echo -e "${RED}Failed to start ChromaDB container${NC}"
        return 1
    }
    
    # Wait for ChromaDB to be ready (check via Docker network using v2 API)
    echo -n "Waiting for ChromaDB"
    for i in {1..30}; do
        if curl -s "http://${GOFR_IQ_CHROMADB_HOST}:${GOFR_IQ_CHROMADB_PORT}/api/v1/heartbeat" >/dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo -e " ${RED}✗${NC}"
    echo -e "${RED}ChromaDB failed to start${NC}"
    docker logs gofr-iq-chromadb 2>&1 | tail -20 || true
    return 1
}

start_vault() {
    echo -e "${YELLOW}Starting Vault container...${NC}"
    
    # Check if container already running
    if docker ps --format '{{.Names}}' | grep -q "^gofr-vault$"; then
        echo -e "${GREEN}Vault container already running${NC}"
        return 0
    fi
    
    # Use gofr-common vault run script
    local vault_script="${PROJECT_ROOT}/lib/gofr-common/docker/infra/vault/run.sh"
    if [ -f "$vault_script" ]; then
        bash "$vault_script" --test
    else
        # Fallback: start directly
        docker run -d \
            --name gofr-vault \
            --hostname gofr-vault \
            --network gofr-net \
            -p 8201:8200 \
            -e VAULT_DEV_ROOT_TOKEN_ID="${GOFR_VAULT_TOKEN}" \
            -e VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200 \
            hashicorp/vault:1.15.6 server -dev >/dev/null 2>&1 || {
            echo -e "${RED}Failed to start Vault container${NC}"
            return 1
        }
    fi
    
    # Wait for Vault to be ready
    echo -n "Waiting for Vault"
    for i in {1..30}; do
        if docker exec gofr-vault vault status >/dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo -e " ${RED}✗${NC}"
    echo -e "${RED}Vault failed to start${NC}"
    docker logs gofr-vault 2>&1 | tail -20 || true
    return 1
}

# NOTE: Auth bootstrap (creating admin/public groups and tokens) is now handled
# by the pytest session fixture in conftest.py. This ensures:
# 1. Groups/tokens are created with the correct JWT secret (GOFR_JWT_SECRET)
# 2. Groups/tokens are created in the correct Vault (gofr-vault-test)
# 3. All tests share the same auth state
# See: test/conftest.py - bootstrap_auth fixture

start_neo4j() {
    echo -e "${YELLOW}Starting Neo4j container...${NC}"
    
    # Check if container already running
    if docker ps --format '{{.Names}}' | grep -q "^gofr-iq-neo4j$"; then
        echo -e "${GREEN}Neo4j container already running${NC}"
        return 0
    fi
    
    # Start container directly without waiting in the script
    docker run -d \
        --name gofr-iq-neo4j \
        --network gofr-net \
        -p "${GOFR_IQ_NEO4J_BOLT_PORT}:7687" \
        -p 7474:7474 \
        -e NEO4J_AUTH="neo4j/${GOFR_IQ_NEO4J_PASSWORD}" \
        -e NEO4J_PLUGINS='["apoc"]' \
        gofr-iq-neo4j:latest >/dev/null 2>&1 || {
        echo -e "${RED}Failed to start Neo4j container${NC}"
        return 1
    }
    
    # Wait for Neo4j to be ready
    echo -n "Waiting for Neo4j"
    for i in {1..60}; do
        if docker exec gofr-iq-neo4j cypher-shell -u neo4j -p "${GOFR_IQ_NEO4J_PASSWORD}" "RETURN 1" >/dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo -e " ${RED}✗${NC}"
    echo -e "${RED}Neo4j failed to start${NC}"
    docker logs gofr-iq-neo4j 2>&1 | tail -20 || true
    return 1
}

stop_infrastructure() {
    echo -e "${YELLOW}Stopping infrastructure containers...${NC}"
    
    # Use manage-infra.sh to stop test infrastructure
    local manage_script="${PROJECT_ROOT}/docker/manage-infra.sh"
    if [ -f "$manage_script" ]; then
        bash "$manage_script" stop --test 2>/dev/null || true
    else
        # Fallback: stop containers directly
        docker stop gofr-vault-test gofr-iq-chromadb-test gofr-iq-neo4j-test 2>/dev/null || true
        docker rm gofr-vault-test gofr-iq-chromadb-test gofr-iq-neo4j-test 2>/dev/null || true
    fi
    
    echo "Infrastructure containers stopped"
}

start_test_infrastructure() {
    local rebuild="$1"
    echo -e "${GREEN}=== Starting Test Infrastructure via manage-infra.sh ===${NC}"
    
    local manage_script="${PROJECT_ROOT}/docker/manage-infra.sh"
    if [ ! -f "$manage_script" ]; then
        echo -e "${RED}manage-infra.sh not found: ${manage_script}${NC}"
        return 1
    fi
    
    # Rebuild Docker images if requested
    if [ "$rebuild" = true ]; then
        echo -e "${YELLOW}Rebuilding Docker images...${NC}"
        bash "${PROJECT_ROOT}/docker/build-vault.sh" || return 1
        bash "${PROJECT_ROOT}/docker/build-chromadb.sh" || return 1
        bash "${PROJECT_ROOT}/docker/build-neo4j.sh" || return 1
        bash "${PROJECT_ROOT}/docker/build-prod.sh" || return 1
        echo -e "${GREEN}Docker images rebuilt${NC}"
    fi
    
    # Start test infrastructure using manage-infra.sh
    bash "$manage_script" start --test || {
        echo -e "${RED}Failed to start test infrastructure${NC}"
        return 1
    }
    
    # Connect dev container to gofr-test-net so tests can reach test services
    local dev_container="gofr-iq-dev"
    if docker ps --format '{{.Names}}' | grep -q "^${dev_container}$"; then
        if ! docker network inspect gofr-test-net --format '{{range .Containers}}{{.Name}} {{end}}' | grep -q "${dev_container}"; then
            echo -e "${YELLOW}Connecting dev container to gofr-test-net...${NC}"
            docker network connect gofr-test-net "${dev_container}" 2>/dev/null || true
        fi
        echo -e "${GREEN}Dev container connected to gofr-test-net${NC}"
    fi
    
    # Verify all test services are reachable
    verify_test_services || {
        echo -e "${RED}Service verification failed${NC}"
        return 1
    }
    
    echo -e "${GREEN}Test infrastructure started and verified${NC}"
    return 0
}

# Verify all test services are reachable before running tests
verify_test_services() {
    echo -e "${BLUE}=== Verifying Test Services ===${NC}"
    local all_ok=true
    
    # Verify Vault
    echo -n "  Vault (${GOFR_VAULT_URL})... "
    if curl -s --max-time 5 "${GOFR_VAULT_URL}/v1/sys/health" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗ NOT REACHABLE${NC}"
        all_ok=false
    fi
    
    # Verify ChromaDB
    local chromadb_url="http://${GOFR_IQ_CHROMADB_HOST}:${GOFR_IQ_CHROMADB_PORT}"
    echo -n "  ChromaDB (${chromadb_url})... "
    if curl -s --max-time 5 "${chromadb_url}/api/v1/heartbeat" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗ NOT REACHABLE${NC}"
        all_ok=false
    fi
    
    # Verify Neo4j
    local neo4j_url="http://${GOFR_IQ_NEO4J_HOST}:7474"
    echo -n "  Neo4j (${neo4j_url})... "
    if curl -s --max-time 5 "${neo4j_url}" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗ NOT REACHABLE${NC}"
        all_ok=false
    fi
    
    echo ""
    echo -e "${BLUE}Test Service Environment Variables:${NC}"
    echo "  GOFR_VAULT_URL=${GOFR_VAULT_URL}"
    echo "  GOFR_VAULT_TOKEN=${GOFR_VAULT_TOKEN:0:10}..."
    echo "  GOFR_IQ_CHROMADB_HOST=${GOFR_IQ_CHROMADB_HOST}"
    echo "  GOFR_IQ_CHROMADB_PORT=${GOFR_IQ_CHROMADB_PORT}"
    echo "  GOFR_IQ_NEO4J_HOST=${GOFR_IQ_NEO4J_HOST}"
    echo "  GOFR_IQ_NEO4J_BOLT_PORT=${GOFR_IQ_NEO4J_BOLT_PORT}"
    echo ""
    
    if [ "$all_ok" = true ]; then
        echo -e "${GREEN}All test services verified${NC}"
        return 0
    else
        echo -e "${RED}Some test services are not reachable${NC}"
        echo -e "${YELLOW}Hint: Is the dev container connected to gofr-test-net?${NC}"
        return 1
    fi
}

cleanup_environment() {
    echo -e "${YELLOW}Cleaning up test environment...${NC}"
    stop_servers || true
    stop_infrastructure || true
    
    # Remove local ChromaDB state (prevents schema conflicts between test runs)
    if [ -d "${PROJECT_ROOT}/data/storage/chroma" ]; then
        echo -e "${YELLOW}Removing local ChromaDB state...${NC}"
        rm -rf "${PROJECT_ROOT}/data/storage/chroma"
    fi
    
    echo -e "${GREEN}Cleanup complete${NC}"
}

start_mcp_server() {
    local log_file="${LOG_DIR}/${PROJECT_NAME}_mcp_test.log"
    echo -e "${YELLOW}Starting MCP server on port ${GOFR_IQ_MCP_PORT}...${NC}"
    
    free_port "${GOFR_IQ_MCP_PORT}"
    rm -f "${log_file}"

    # Auth backend configured via GOFR_AUTH_BACKEND env var (Vault)
    nohup uv run python app/main_mcp.py \
        --port "${GOFR_IQ_MCP_PORT}" \
        --jwt-secret "${GOFR_IQ_JWT_SECRET}" \
        --log-level INFO \
        > "${log_file}" 2>&1 &
    MCP_PID=$!
    echo "MCP PID: ${MCP_PID}"

    echo -n "Waiting for MCP server"
    for _ in {1..30}; do
        if ! kill -0 ${MCP_PID} 2>/dev/null; then
            echo -e " ${RED}✗${NC}"
            tail -20 "${log_file}"
            return 1
        fi
        if port_in_use "${GOFR_IQ_MCP_PORT}"; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 0.5
    done
    echo -e " ${RED}✗${NC}"
    tail -20 "${log_file}"
    return 1
}

start_web_server() {
    local log_file="${LOG_DIR}/${PROJECT_NAME}_web_test.log"
    echo -e "${YELLOW}Starting Web server on port ${GOFR_IQ_WEB_PORT}...${NC}"
    
    free_port "${GOFR_IQ_WEB_PORT}"
    rm -f "${log_file}"

    # Auth backend configured via GOFR_AUTH_BACKEND env var (Vault)
    nohup uv run python app/main_web.py \
        --port "${GOFR_IQ_WEB_PORT}" \
        --jwt-secret "${GOFR_IQ_JWT_SECRET}" \
        > "${log_file}" 2>&1 &
    WEB_PID=$!
    echo "Web PID: ${WEB_PID}"

    echo -n "Waiting for Web server"
    for _ in {1..30}; do
        if ! kill -0 ${WEB_PID} 2>/dev/null; then
            echo -e " ${RED}✗${NC}"
            tail -20 "${log_file}"
            return 1
        fi
        if port_in_use "${GOFR_IQ_WEB_PORT}"; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 0.5
    done
    echo -e " ${RED}✗${NC}"
    tail -20 "${log_file}"
    return 1
}

start_mcpo_server() {
    local log_file="${LOG_DIR}/${PROJECT_NAME}_mcpo_test.log"
    echo -e "${YELLOW}Starting MCPO server on port ${GOFR_IQ_MCPO_PORT}...${NC}"
    
    free_port "${GOFR_IQ_MCPO_PORT}"
    rm -f "${log_file}"

    # MCPO wraps the MCP server and exposes it as REST/OpenAPI
    # Connect to the already-running MCP server via HTTP Streamable transport
    # NEVER use stdio or SSE - only HTTP Streamable!
    # Matches docker-compose.yml: mcpo --server-type streamable-http -- http://host:port/mcp
    # NOTE: No --api-key - MCPO is a transparent pass-through, MCP validates JWTs
    local mcp_url="http://localhost:${GOFR_IQ_MCP_PORT}/mcp"
    
    nohup mcpo --host 0.0.0.0 --port "${GOFR_IQ_MCPO_PORT}" \
        --server-type streamable-http \
        -- "${mcp_url}" \
        > "${log_file}" 2>&1 &
    MCPO_PID=$!
    echo "MCPO PID: ${MCPO_PID}"

    echo -n "Waiting for MCPO server"
    for _ in {1..30}; do
        if ! kill -0 ${MCPO_PID} 2>/dev/null; then
            echo -e " ${RED}✗${NC}"
            echo "MCPO process died, checking logs:"
            tail -30 "${log_file}"
            return 1
        fi
        # Use /docs endpoint like docker healthcheck
        if curl -s "http://localhost:${GOFR_IQ_MCPO_PORT}/docs" >/dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            return 0
        fi
        echo -n "."
        sleep 0.5
    done
    echo -e " ${RED}✗${NC}"
    echo "MCPO server logs:"
    tail -30 "${log_file}"
    return 1
}

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

USE_DOCKER=false
START_SERVERS=true
COVERAGE=false
COVERAGE_HTML=false
RUN_UNIT=false
RUN_INTEGRATION=false
RUN_ALL=false
STOP_ONLY=false
CLEANUP_ONLY=false
REBUILD_IMAGES=false
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker)
            USE_DOCKER=true
            shift
            ;;
        --coverage|--cov)
            COVERAGE=true
            shift
            ;;
        --coverage-html)
            COVERAGE=true
            COVERAGE_HTML=true
            shift
            ;;
        --unit)
            RUN_UNIT=true
            START_SERVERS=false
            shift
            ;;
        --integration)
            RUN_INTEGRATION=true
            START_SERVERS=true
            shift
            ;;
        --all)
            RUN_ALL=true
            START_SERVERS=true
            shift
            ;;
        --no-servers|--without-servers)
            START_SERVERS=false
            shift
            ;;
        --with-servers|--start-servers)
            START_SERVERS=true
            shift
            ;;
        --rebuild)
            REBUILD_IMAGES=true
            shift
            ;;
        --stop|--stop-servers)
            STOP_ONLY=true
            shift
            ;;
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [PYTEST_ARGS...]"
            echo ""
            echo "Options:"
            echo "  --docker         Run tests inside Docker container"
            echo "  --coverage       Run with coverage report"
            echo "  --coverage-html  Run with HTML coverage report"
            echo "  --unit           Run unit tests only (no servers)"
            echo "  --integration    Run integration tests (with servers)"
            echo "  --all            Run all test categories"
            echo "  --no-servers     Don't start test servers"
            echo "  --with-servers   Start test servers (default)"
            echo "  --rebuild        Rebuild Docker images before starting"
            echo "  --stop           Stop servers and exit"
            echo "  --cleanup-only   Clean environment and exit"
            echo "  --help, -h       Show this help message"
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

# =============================================================================
# MAIN EXECUTION
# =============================================================================

print_header

# Handle stop-only mode
if [ "$STOP_ONLY" = true ]; then
    echo -e "${YELLOW}Stopping servers and exiting...${NC}"
    stop_servers
    exit 0
fi

# Handle cleanup-only mode
if [ "$CLEANUP_ONLY" = true ]; then
    cleanup_environment
    exit 0
fi

# Only run full cleanup for integration tests (skip for unit tests)
if [ "$RUN_UNIT" = true ]; then
    echo -e "${YELLOW}Unit test mode - skipping server cleanup${NC}"
else
    # Clean up before starting
    cleanup_environment
fi

# Start servers if needed
MCP_PID=""
WEB_PID=""
MCPO_PID=""
if [ "$START_SERVERS" = true ] && [ "$USE_DOCKER" = false ]; then
    # Start test infrastructure via manage-infra.sh (Vault, ChromaDB, Neo4j)
    start_test_infrastructure "$REBUILD_IMAGES" || { stop_servers; stop_infrastructure; exit 1; }
    
    # NOTE: Auth bootstrap (admin/public groups & tokens) happens in conftest.py
    # This ensures tokens are created with correct JWT secret after Vault is ready
    echo -e "${BLUE}Auth bootstrap will run in pytest session fixture (conftest.py)${NC}"
    echo ""
    
    echo -e "${GREEN}=== Starting Test Servers ===${NC}"
    start_mcp_server || { stop_servers; stop_infrastructure; exit 1; }
    start_web_server || { stop_servers; stop_infrastructure; exit 1; }
    start_mcpo_server || { stop_servers; stop_infrastructure; exit 1; }
    echo ""
fi

# Build coverage arguments
COVERAGE_ARGS=""
if [ "$COVERAGE" = true ]; then
    COVERAGE_ARGS="--cov=${COVERAGE_SOURCE} --cov-report=term-missing"
    if [ "$COVERAGE_HTML" = true ]; then
        COVERAGE_ARGS="${COVERAGE_ARGS} --cov-report=html:htmlcov"
    fi
    echo -e "${BLUE}Coverage reporting enabled${NC}"
fi

# =============================================================================
# RUN TESTS
# =============================================================================

# Run version compatibility check first
echo -e "${GREEN}=== Checking Version Compatibility ===${NC}"
if ! python "${SCRIPT_DIR}/check_version_compatibility.py"; then
    echo -e "${RED}Version compatibility check failed!${NC}"
    echo "Fix version mismatches before running tests."
    [ "$START_SERVERS" = true ] && [ "$USE_DOCKER" = false ] && stop_infrastructure || true
    exit 1
fi
echo ""

echo -e "${GREEN}=== Running Tests ===${NC}"
set +e
TEST_EXIT_CODE=0

if [ "$USE_DOCKER" = true ]; then
    # Docker execution
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${RED}Container ${CONTAINER_NAME} is not running.${NC}"
        echo "Run: ./docker/run-dev.sh to create it"
        exit 1
    fi
    
    DOCKER_CMD="cd /home/gofr/devroot/${PROJECT_NAME} && source .venv/bin/activate && pytest ${TEST_DIR}/ -v ${COVERAGE_ARGS}"
    docker exec "${CONTAINER_NAME}" bash -c "${DOCKER_CMD}"
    TEST_EXIT_CODE=$?

elif [ "$RUN_UNIT" = true ]; then
    echo -e "${BLUE}Running unit tests only (no servers)...${NC}"
    uv run python -m pytest ${TEST_DIR}/ -v ${COVERAGE_ARGS} -k "not integration"
    TEST_EXIT_CODE=$?

elif [ "$RUN_INTEGRATION" = true ]; then
    echo -e "${BLUE}Running integration tests (with servers)...${NC}"
    uv run python -m pytest ${TEST_DIR}/ -v ${COVERAGE_ARGS}
    TEST_EXIT_CODE=$?

elif [ "$RUN_ALL" = true ]; then
    echo -e "${BLUE}Running ALL tests...${NC}"
    uv run python -m pytest ${TEST_DIR}/ -v ${COVERAGE_ARGS}
    TEST_EXIT_CODE=$?

elif [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    # Default: run all tests
    uv run python -m pytest ${TEST_DIR}/ -v ${COVERAGE_ARGS}
    TEST_EXIT_CODE=$?
else
    # Custom arguments
    uv run python -m pytest "${PYTEST_ARGS[@]}" ${COVERAGE_ARGS}
    TEST_EXIT_CODE=$?
fi
set -e

# =============================================================================
# CLEANUP
# =============================================================================

if [ "$START_SERVERS" = true ] && [ "$USE_DOCKER" = false ]; then
    echo ""
    echo -e "${YELLOW}Stopping test servers...${NC}"
    stop_servers || true
    echo -e "${YELLOW}Stopping infrastructure containers...${NC}"
    stop_infrastructure || true
fi

# Clean up token store
echo -e "${YELLOW}Cleaning up token store...${NC}"
echo "{}" > "${GOFR_IQ_TOKEN_STORE}" 2>/dev/null || true

# =============================================================================
# RESULTS
# =============================================================================

echo ""
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}=== Tests Passed ===${NC}"
    if [ "$COVERAGE" = true ] && [ "$COVERAGE_HTML" = true ]; then
        echo -e "${BLUE}HTML coverage report: ${PROJECT_ROOT}/htmlcov/index.html${NC}"
    fi
else
    echo -e "${RED}=== Tests Failed (exit code: ${TEST_EXIT_CODE}) ===${NC}"
    echo "Server logs:"
    echo "  MCP: ${LOG_DIR}/${PROJECT_NAME}_mcp_test.log"
    echo "  Web: ${LOG_DIR}/${PROJECT_NAME}_web_test.log"
fi

exit $TEST_EXIT_CODE
