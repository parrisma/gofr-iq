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

# Source centralized environment configuration
export GOFR_IQ_ENV="TEST"
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

# Test configuration - use standardized GOFR_IQ_ prefix
export GOFR_IQ_JWT_SECRET="test-secret-key-for-secure-testing-do-not-use-in-production"
export GOFR_IQ_TOKEN_STORE="${GOFR_IQ_TOKEN_STORE:-${LOG_DIR}/${PROJECT_NAME}_tokens_test.json}"
# Test ports are intentionally different from production (8080/8081/8082) to avoid conflicts
export GOFR_IQ_MCP_PORT="${GOFR_IQ_MCP_PORT:-8180}"
export GOFR_IQ_WEB_PORT="${GOFR_IQ_WEB_PORT:-8182}"
export GOFR_IQ_MCPO_PORT="${GOFR_IQ_MCPO_PORT:-8181}"

# Infrastructure (ChromaDB, Neo4j) - for tests connecting to external services
# Use container names on gofr-net network (not localhost, since we're in a container)
export GOFR_IQ_CHROMA_HOST="${GOFR_IQ_CHROMA_HOST:-gofr-iq-chromadb}"
export GOFR_IQ_CHROMA_PORT="${GOFR_IQ_CHROMA_PORT:-8000}"
export GOFR_IQ_NEO4J_HOST="${GOFR_IQ_NEO4J_HOST:-gofr-iq-neo4j}"
export GOFR_IQ_NEO4J_BOLT_PORT="${GOFR_IQ_NEO4J_BOLT_PORT:-7687}"
export GOFR_IQ_NEO4J_PASSWORD="${GOFR_IQ_NEO4J_PASSWORD:-testpassword}"

# Legacy variable mapping for backward compatibility
export GOFR_IQ_JWT_SECRET="${GOFR_IQ_JWT_SECRET}"
export GOFR_IQ_TOKEN_STORE="${GOFR_IQ_TOKEN_STORE}"
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
    echo "Token store: ${GOFR_IQ_TOKEN_STORE}"
    echo "MCP Port: ${GOFR_IQ_MCP_PORT}"
    echo "Web Port: ${GOFR_IQ_WEB_PORT}"
    echo "ChromaDB: ${GOFR_IQ_CHROMA_HOST}:${GOFR_IQ_CHROMA_PORT}"
    echo "Neo4j: ${GOFR_IQ_NEO4J_HOST}:${GOFR_IQ_NEO4J_BOLT_PORT}"
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
    pkill -9 -f "python.*main_mcp" 2>/dev/null || true
    pkill -9 -f "python.*main_web" 2>/dev/null || true
    pkill -9 -f "mcpo" 2>/dev/null || true
    sleep 2
    
    if ps aux | grep -E "python.*(main_mcp|main_web)|mcpo" | grep -v grep >/dev/null 2>&1; then
        echo -e "${RED}WARNING: Some server processes still running${NC}"
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
        -p "${GOFR_IQ_CHROMA_PORT}:8000" \
        gofr-iq-chromadb:latest >/dev/null 2>&1 || {
        echo -e "${RED}Failed to start ChromaDB container${NC}"
        return 1
    }
    
    # Wait for ChromaDB to be ready (check via Docker network using v2 API)
    echo -n "Waiting for ChromaDB"
    for i in {1..30}; do
        if curl -s "http://${GOFR_IQ_CHROMA_HOST}:${GOFR_IQ_CHROMA_PORT}/api/v2/heartbeat" >/dev/null 2>&1; then
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
    
    # Stop ChromaDB if running
    if docker ps --format '{{.Names}}' | grep -q "^gofr-iq-chromadb$"; then
        docker stop gofr-iq-chromadb >/dev/null 2>&1 || true
        docker rm gofr-iq-chromadb >/dev/null 2>&1 || true
    fi
    
    # Stop Neo4j if running
    if docker ps --format '{{.Names}}' | grep -q "^gofr-iq-neo4j$"; then
        docker stop gofr-iq-neo4j >/dev/null 2>&1 || true
        docker rm gofr-iq-neo4j >/dev/null 2>&1 || true
    fi
    
    echo "Infrastructure containers stopped"
}

cleanup_environment() {
    echo -e "${YELLOW}Cleaning up test environment...${NC}"
    stop_servers || true
    stop_infrastructure || true
    
    # Empty token store
    echo "{}" > "${GOFR_IQ_TOKEN_STORE}" 2>/dev/null || true
    echo "Token store emptied: ${GOFR_IQ_TOKEN_STORE}"
    
    echo -e "${GREEN}Cleanup complete${NC}"
}

start_mcp_server() {
    local log_file="${LOG_DIR}/${PROJECT_NAME}_mcp_test.log"
    echo -e "${YELLOW}Starting MCP server on port ${GOFR_IQ_MCP_PORT}...${NC}"
    
    free_port "${GOFR_IQ_MCP_PORT}"
    rm -f "${log_file}"

    nohup uv run python app/main_mcp.py \
        --port "${GOFR_IQ_MCP_PORT}" \
        --jwt-secret "${GOFR_IQ_JWT_SECRET}" \
        --token-store "${GOFR_IQ_TOKEN_STORE}" \
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

    nohup uv run python app/main_web.py \
        --port "${GOFR_IQ_WEB_PORT}" \
        --jwt-secret "${GOFR_IQ_JWT_SECRET}" \
        --token-store "${GOFR_IQ_TOKEN_STORE}" \
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

# Clean up before starting
cleanup_environment

# Initialize token store
if [ ! -f "${GOFR_IQ_TOKEN_STORE}" ]; then
    echo "{}" > "${GOFR_IQ_TOKEN_STORE}"
fi

# Start servers if needed
MCP_PID=""
WEB_PID=""
if [ "$START_SERVERS" = true ] && [ "$USE_DOCKER" = false ]; then
    echo -e "${GREEN}=== Starting Test Infrastructure ===${NC}"
    
    # Start infrastructure containers
    start_chromadb || { stop_servers; stop_infrastructure; exit 1; }
    start_neo4j || { stop_servers; stop_infrastructure; exit 1; }
    echo ""
    
    echo -e "${GREEN}=== Starting Test Servers ===${NC}"
    start_mcp_server || { stop_servers; stop_infrastructure; exit 1; }
    start_web_server || { stop_servers; stop_infrastructure; exit 1; }
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
