#!/bin/bash
# =============================================================================
# GOFR-IQ Test Runner
# =============================================================================
# Runs full test suite with ephemeral test infrastructure (docker-compose-test.yml).
#
# Usage:
#   ./scripts/run_tests.sh                    # Run all tests
#   ./scripts/run_tests.sh test/test_auth*.py # Run specific tests
#   ./scripts/run_tests.sh -k "ingest"        # Run tests matching keyword
#   ./scripts/run_tests.sh --coverage         # Run with coverage report
#   ./scripts/run_tests.sh --stop             # Stop test infrastructure
#   ./scripts/run_tests.sh --cleanup-only     # Clean up containers/volumes
#   ./scripts/run_tests.sh --check            # Pre-flight check only (no tests)
#
# Secrets (can be passed via environment or command line):
#   --api-key KEY         Set GOFR_IQ_OPENROUTER_API_KEY (required for LLM tests)
#   --jwt-secret SECRET   Set GOFR_JWT_SECRET (auto-generated if not set)
#   --neo4j-password PWD  Set GOFR_IQ_NEO4J_PASSWORD (default: testpassword)
#
# Infrastructure:
#   - Vault (gofr-vault-test) - Auth backend
#   - Neo4j (gofr-iq-neo4j-test) - Graph database
#   - ChromaDB (gofr-iq-chromadb-test) - Vector database
#   - MCP/MCPO/Web test servers
#
# All test ports are offset by +100 from production (see gofr_ports.env).
#
# =============================================================================
# REQUIRED ENVIRONMENT VARIABLES
# =============================================================================
# These are typically loaded from lib/gofr-common/.env:
#
#   GOFR_IQ_OPENROUTER_API_KEY  - OpenRouter API key (REQUIRED - pass via --api-key or env)
#                                  MCP server will not start without this
#   GOFR_JWT_SECRET             - JWT signing secret (auto-generated if not set)
#   GOFR_IQ_NEO4J_PASSWORD      - Neo4j password (default: testpassword)
#   GOFR_IQ_LLM_MODEL           - LLM model (default: meta-llama/llama-3.1-70b-instruct)
#
# =============================================================================
# SKIP CONDITIONS
# =============================================================================
# Tests may be skipped under these conditions:
#
# 1. GOFR_IQ_OPENROUTER_API_KEY not set:
#    - test_integration_llm.py (all tests) - LLM integration tests
#    - test_end_to_end_ingest_query.py - E2E ingest/query tests with real LLM
#
# 2. Neo4j not available (bolt://gofr-iq-neo4j-test:7687):
#    - test_graph_index.py (all tests) - Graph database tests
#
# 3. MCPO server not running:
#    - test_mcpo_group_access.py - Group-based access control tests
#    - test_vault_integration.py::test_jwt_reaches_mcp_tools_via_mcpo
#
# 4. Vault backend not configured (GOFR_AUTH_BACKEND != "vault"):
#    - test_vault_integration.py::TestVaultBackend (all tests)
#
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Project config
PROJECT_NAME="gofr-iq"
TEST_DIR="test"
COVERAGE_SOURCE="app"
LOG_DIR="${PROJECT_ROOT}/logs"
TEST_ENV_SCRIPT="${SCRIPT_DIR}/test_env.sh"
TEST_SERVERS_SCRIPT="${SCRIPT_DIR}/test_servers.sh"

# State tracking
USE_DOCKER=false
COVERAGE=false
COVERAGE_HTML=false
STOP_ONLY=false
CLEANUP_ONLY=false
REBUILD_IMAGES=false
CHECK_ONLY=false
INCLUDE_E2E=false
PYTEST_ARGS=()
TEST_ENV_STARTED=false
TEST_SERVERS_STARTED=false
CLEANUP_IN_PROGRESS=false

# Command-line overrides (applied after .env loading)
CLI_API_KEY=""
CLI_JWT_SECRET=""
CLI_NEO4J_PASSWORD=""

# Activate virtual environment
VENV_DIR="${PROJECT_ROOT}/.venv"
if [ -f "${VENV_DIR}/bin/activate" ]; then
    source "${VENV_DIR}/bin/activate"
    echo "Activated venv: ${VENV_DIR}"
fi

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

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
        --check)
            CHECK_ONLY=true
            shift
            ;;
        --e2e)
            INCLUDE_E2E=true
            shift
            ;;
        --api-key)
            CLI_API_KEY="$2"
            shift 2
            ;;
        --jwt-secret)
            CLI_JWT_SECRET="$2"
            shift 2
            ;;
        --neo4j-password)
            CLI_NEO4J_PASSWORD="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [PYTEST_ARGS...]"
            echo ""
            echo "Options:"
            echo "  --docker            Run tests inside the dev container"
            echo "  --coverage          Enable coverage (terminal report)"
            echo "  --coverage-html     Add HTML coverage report"
            echo "  --rebuild           Rebuild Docker images before tests"
            echo "  --stop              Stop test servers and exit"
            echo "  --cleanup-only      Clean environment and exit"
            echo "  --check             Pre-flight check only (verify secrets, no tests)"
            echo "  --e2e               Include live e2e tests (requires OpenRouter key)"
            echo "  --help, -h          Show this help message"
            echo ""
            echo "Secrets (can also be set via environment or lib/gofr-common/.env):"
            echo "  --api-key KEY       Set GOFR_IQ_OPENROUTER_API_KEY (required for LLM tests)"
            echo "  --jwt-secret SECRET Set GOFR_JWT_SECRET (auto-generated if not set)"
            echo "  --neo4j-password P  Set GOFR_IQ_NEO4J_PASSWORD (default: testpassword)"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Run all tests"
            echo "  $0 test/test_auth*.py                 # Run specific tests"
            echo "  $0 -k 'ingest'                        # Run tests matching keyword"
            echo "  $0 --coverage                         # Run with coverage"
            echo "  $0 --api-key sk-or-v1-xxxxx           # Run with explicit API key"
            echo "  $0 --check                            # Verify environment only"
            echo ""
            echo "Required secrets (see header for skip conditions):"
            echo "  GOFR_IQ_OPENROUTER_API_KEY - Required for LLM tests (costs ~\$0.01-0.05)"
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================

export GOFR_IQ_ENV="TEST"

# Load port configuration
GOFR_PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
if [ -f "${GOFR_PORTS_FILE}" ]; then
    echo "Loading port configuration from gofr_ports.env"
    set -a
    source "${GOFR_PORTS_FILE}"
    set +a
    
    # Apply test port offsets (+100)
    export GOFR_IQ_MCP_PORT="${GOFR_IQ_MCP_PORT_TEST:-$((GOFR_IQ_MCP_PORT + 100))}"
    export GOFR_IQ_MCPO_PORT="${GOFR_IQ_MCPO_PORT_TEST:-$((GOFR_IQ_MCPO_PORT + 100))}"
    export GOFR_IQ_WEB_PORT="${GOFR_IQ_WEB_PORT_TEST:-$((GOFR_IQ_WEB_PORT + 100))}"
    export GOFR_VAULT_PORT="${GOFR_VAULT_PORT_TEST:-$((GOFR_VAULT_PORT + 100))}"
    export GOFR_CHROMA_PORT="${GOFR_CHROMA_PORT_TEST:-$((GOFR_CHROMA_PORT + 100))}"
    export GOFR_NEO4J_HTTP_PORT="${GOFR_NEO4J_HTTP_PORT_TEST:-$((GOFR_NEO4J_HTTP_PORT + 100))}"
    export GOFR_NEO4J_BOLT_PORT="${GOFR_NEO4J_BOLT_PORT_TEST:-$((GOFR_NEO4J_BOLT_PORT + 100))}"
    
    echo "  Port configuration loaded (test mode with +100 offset)"
else
    echo -e "${RED}ERROR: Port configuration not found: ${GOFR_PORTS_FILE}${NC}" >&2
    exit 1
fi

# Load secrets from gofr-common .env
GOFR_COMMON_ENV="${PROJECT_ROOT}/lib/gofr-common/.env"
if [ -f "${GOFR_COMMON_ENV}" ]; then
    set -a
    source "${GOFR_COMMON_ENV}"
    set +a
    echo "Loaded secrets from gofr-common/.env"
fi

# Apply command-line overrides (take precedence over .env)
if [ -n "${CLI_API_KEY}" ]; then
    export GOFR_IQ_OPENROUTER_API_KEY="${CLI_API_KEY}"
    echo "  Using API key from command line"
fi
if [ -n "${CLI_JWT_SECRET}" ]; then
    export GOFR_JWT_SECRET="${CLI_JWT_SECRET}"
    echo "  Using JWT secret from command line"
fi
if [ -n "${CLI_NEO4J_PASSWORD}" ]; then
    export GOFR_IQ_NEO4J_PASSWORD="${CLI_NEO4J_PASSWORD}"
    echo "  Using Neo4j password from command line"
fi

# Set defaults
export GOFR_VAULT_DEV_TOKEN="${GOFR_VAULT_DEV_TOKEN:-gofr-dev-root-token}"
if [ -z "${GOFR_JWT_SECRET:-}" ]; then
    export GOFR_JWT_SECRET="test-jwt-secret-$(date +%s)"
fi
echo "  JWT Secret: ${GOFR_JWT_SECRET:0:20}..."

# OpenRouter API Key - REQUIRED (like start-prod.sh)
# Must be passed via --api-key or GOFR_IQ_OPENROUTER_API_KEY env var.
# Not stored in .env because keys are opaque and expire silently.
if [ -n "${GOFR_IQ_OPENROUTER_API_KEY:-}" ]; then
    echo "  OpenRouter API Key: ${GOFR_IQ_OPENROUTER_API_KEY:0:15}...${GOFR_IQ_OPENROUTER_API_KEY: -4}"
else
    echo -e "${RED}ERROR: GOFR_IQ_OPENROUTER_API_KEY is required.${NC}" >&2
    echo "" >&2
    echo "The MCP server and LLM tests need an OpenRouter API key." >&2
    echo "Get one from: https://openrouter.ai/keys" >&2
    echo "" >&2
    echo "Pass it via:" >&2
    echo "  $0 --api-key sk-or-v1-xxxxx" >&2
    echo "  # or:" >&2
    echo "  export GOFR_IQ_OPENROUTER_API_KEY=sk-or-v1-xxxxx" >&2
    exit 1
fi

# Vault configuration (tests connect via container network)
export GOFR_AUTH_BACKEND="vault"
export GOFR_VAULT_URL="http://gofr-vault-test:8200"
export GOFR_VAULT_TOKEN="${GOFR_VAULT_DEV_TOKEN}"
export VAULT_ADDR="http://gofr-vault-test:8200"
export VAULT_TOKEN="${GOFR_VAULT_DEV_TOKEN}"

# Infrastructure hostnames (container network)
export GOFR_IQ_CHROMADB_HOST="gofr-iq-chromadb-test"
export GOFR_IQ_CHROMADB_PORT="8000"
export GOFR_IQ_NEO4J_HOST="gofr-iq-neo4j-test"
export GOFR_IQ_NEO4J_BOLT_PORT="7687"
export GOFR_IQ_NEO4J_URI="bolt://gofr-iq-neo4j-test:7687"
export GOFR_IQ_NEO4J_PASSWORD="${GOFR_IQ_NEO4J_PASSWORD:-testpassword}"
# CRITICAL: Force NEO4J_PASSWORD to match GOFR_IQ_NEO4J_PASSWORD.
# docker-compose-test.yml reads NEO4J_PASSWORD for the Neo4j container auth.
# Without this, a stale production password from `source docker/.env` leaks in
# and causes auth mismatch between Neo4j container and host MCP server.
export NEO4J_PASSWORD="${GOFR_IQ_NEO4J_PASSWORD}"

# Legacy aliases
export GOFR_IQ_JWT_SECRET="${GOFR_JWT_SECRET}"

# PYTHONPATH
if [ -d "${PROJECT_ROOT}/lib/gofr-common/src" ]; then
    export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/lib/gofr-common/src:${PYTHONPATH:-}"
else
    export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
fi

mkdir -p "${LOG_DIR}"

# =============================================================================
# PRE-FLIGHT CHECK
# =============================================================================

preflight_check() {
    echo -e "${GREEN}=== Pre-flight Environment Check ===${NC}"
    local warnings=0
    local errors=0
    
    echo ""
    echo -e "${BLUE}Required Secrets:${NC}"
    
    # Check OpenRouter API Key (required - script exits before here if missing)
    if [ -n "${GOFR_IQ_OPENROUTER_API_KEY:-}" ]; then
        echo -e "  ${GREEN}[ok]${NC} GOFR_IQ_OPENROUTER_API_KEY: ${GOFR_IQ_OPENROUTER_API_KEY:0:15}...${GOFR_IQ_OPENROUTER_API_KEY: -4}"
    fi
    
    # Check JWT Secret
    if [ -n "${GOFR_JWT_SECRET:-}" ]; then
        echo -e "  ${GREEN}✓${NC} GOFR_JWT_SECRET: ${GOFR_JWT_SECRET:0:20}..."
    else
        echo -e "  ${RED}✗${NC} GOFR_JWT_SECRET: NOT SET (will be auto-generated)"
    fi
    
    # Check Neo4j password
    echo -e "  ${GREEN}✓${NC} GOFR_IQ_NEO4J_PASSWORD: ${GOFR_IQ_NEO4J_PASSWORD:-testpassword} (default: testpassword)"
    
    echo ""
    echo -e "${BLUE}Infrastructure (will be started by test runner):${NC}"
    echo "  Vault:    gofr-vault-test:8200"
    echo "  Neo4j:    gofr-iq-neo4j-test:7687"
    echo "  ChromaDB: gofr-iq-chromadb-test:8000"
    echo "  MCP:      localhost:${GOFR_IQ_MCP_PORT}"
    echo "  MCPO:     localhost:${GOFR_IQ_MCPO_PORT}"
    echo "  Web:      localhost:${GOFR_IQ_WEB_PORT}"
    
    echo ""
    echo -e "${BLUE}Optional Settings:${NC}"
    echo "  GOFR_IQ_LLM_MODEL: ${GOFR_IQ_LLM_MODEL:-meta-llama/llama-3.1-70b-instruct}"
    echo "  GOFR_AUTH_BACKEND: ${GOFR_AUTH_BACKEND:-vault}"
    
    echo ""
    echo -e "${BLUE}Source Files:${NC}"
    if [ -f "${GOFR_COMMON_ENV}" ]; then
        echo -e "  ${GREEN}✓${NC} ${GOFR_COMMON_ENV}"
    else
        echo -e "  ${YELLOW}⚠${NC} ${GOFR_COMMON_ENV} (not found - using defaults)"
        ((warnings++))
    fi
    if [ -f "${GOFR_PORTS_FILE}" ]; then
        echo -e "  ${GREEN}✓${NC} ${GOFR_PORTS_FILE}"
    else
        echo -e "  ${RED}✗${NC} ${GOFR_PORTS_FILE} (REQUIRED)"
        ((errors++))
    fi
    
    echo ""
    if [ $errors -gt 0 ]; then
        echo -e "${RED}Pre-flight check FAILED: $errors error(s), $warnings warning(s)${NC}"
        return 1
    elif [ $warnings -gt 0 ]; then
        echo -e "${YELLOW}Pre-flight check PASSED with $warnings warning(s)${NC}"
        echo -e "${YELLOW}Some tests may be skipped. See above for details.${NC}"
        return 0
    else
        echo -e "${GREEN}Pre-flight check PASSED${NC}"
        return 0
    fi
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

run_test_env_cmd() {
    local action="$1"
    shift || true
    if [ ! -x "${TEST_ENV_SCRIPT}" ]; then
        echo -e "${RED}ERROR: Test environment helper not found: ${TEST_ENV_SCRIPT}${NC}" >&2
        return 1
    fi
    bash "${TEST_ENV_SCRIPT}" "${action}" "$@"
}

run_test_servers_cmd() {
    local action="$1"
    shift || true
    if [ ! -x "${TEST_SERVERS_SCRIPT}" ]; then
        echo -e "${RED}ERROR: Test server helper not found: ${TEST_SERVERS_SCRIPT}${NC}" >&2
        return 1
    fi
    bash "${TEST_SERVERS_SCRIPT}" "${action}" "$@"
}

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

stop_servers() {
    echo "Stopping server processes..."
    run_test_servers_cmd stop || true

    pkill -f "app/main_mcp\.py" 2>/dev/null || true
    pkill -f "app/main_web\.py" 2>/dev/null || true
    pkill -f "app/main_mcpo\.py" 2>/dev/null || true

    sleep 1
    echo "All server processes stopped"
}

cleanup_environment() {
    local exit_code=$?
    if [ "$CLEANUP_IN_PROGRESS" = true ]; then
        return $exit_code
    fi
    CLEANUP_IN_PROGRESS=true

    if [ "$TEST_SERVERS_STARTED" = true ]; then
        stop_servers || true
    fi

    if [ "$TEST_ENV_STARTED" = true ]; then
        echo "Stopping test infrastructure..."
        run_test_env_cmd stop || true
    fi

    # Clean dangling volumes
    echo "Checking for orphaned Docker volumes..."
    local dangling_volumes
    dangling_volumes=$(docker volume ls -qf dangling=true 2>/dev/null || true)
    if [ -n "$dangling_volumes" ]; then
        echo "Removing dangling Docker volumes..."
        echo "$dangling_volumes" | xargs -r docker volume rm 2>/dev/null || true
    else
        echo "No dangling Docker volumes found"
    fi

    CLEANUP_IN_PROGRESS=false
    return $exit_code
}

trap cleanup_environment EXIT INT TERM

# =============================================================================
# MAIN EXECUTION
# =============================================================================

print_header

# Run pre-flight check
preflight_check
PREFLIGHT_STATUS=$?

# Handle check-only mode
if [ "$CHECK_ONLY" = true ]; then
    exit $PREFLIGHT_STATUS
fi

# Handle stop-only mode
if [ "$STOP_ONLY" = true ]; then
    echo -e "${YELLOW}Stopping servers and exiting...${NC}"
    stop_servers
    run_test_env_cmd stop || true
    exit 0
fi

# Handle cleanup-only mode
if [ "$CLEANUP_ONLY" = true ]; then
    TEST_ENV_STARTED=true
    TEST_SERVERS_STARTED=true
    cleanup_environment
    exit 0
fi

# Stop any existing servers
if [ "$USE_DOCKER" = false ]; then
    echo -e "${BLUE}Ensuring MCP/MCPO/Web servers are not already running...${NC}"
    stop_servers
fi

# Start test infrastructure
if [ "$USE_DOCKER" = false ]; then
    echo -e "${GREEN}Starting GOFR-IQ test infrastructure...${NC}"
    
    TEST_ENV_ARGS=()
    if [ "$REBUILD_IMAGES" = true ]; then
        TEST_ENV_ARGS+=(--rebuild)
    fi
    
    if run_test_env_cmd start "${TEST_ENV_ARGS[@]}"; then
        TEST_ENV_STARTED=true
    else
        run_test_env_cmd stop || true
        exit 1
    fi
    
    # Initialize test Vault with JWT secret
    echo -e "${BLUE}Initializing test Vault with JWT secret...${NC}"
    if curl -sf -X POST \
        -H "X-Vault-Token: ${VAULT_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"data\": {\"value\": \"${GOFR_JWT_SECRET}\"}}" \
        "${VAULT_ADDR}/v1/secret/data/gofr/config/jwt-signing-secret" >/dev/null 2>&1; then
        echo -e "${GREEN}  JWT secret stored in test Vault${NC}"
    else
        echo -e "${YELLOW}  Warning: Could not store JWT in Vault${NC}"
    fi
    
    echo -e "${BLUE}Auth bootstrap will run in pytest session fixture (conftest.py)${NC}"
    echo ""
    
    # Bootstrap graph schema + taxonomy (same as prod)
    echo -e "${GREEN}=== Bootstrapping Graph Schema ===${NC}"
    if uv run python "${SCRIPT_DIR}/bootstrap_graph.py" --verbose; then
        echo -e "${GREEN}  Graph schema bootstrapped successfully${NC}"
    else
        echo -e "${RED}  Graph bootstrap failed!${NC}"
        run_test_env_cmd stop || true
        exit 1
    fi
    echo ""
    
    # Start test servers (MCP/MCPO/Web)
    echo -e "${GREEN}=== Starting Test Servers ===${NC}"
    if run_test_servers_cmd start; then
        TEST_SERVERS_STARTED=true
    else
        stop_servers
        run_test_env_cmd stop || true
        exit 1
    fi
    echo ""
fi

# Build coverage arguments
COVERAGE_ARGS=()
if [ "$COVERAGE" = true ]; then
    COVERAGE_ARGS+=("--cov=${COVERAGE_SOURCE}" "--cov-report=term-missing")
    if [ "$COVERAGE_HTML" = true ]; then
        COVERAGE_ARGS+=("--cov-report=html:htmlcov")
    fi
    echo -e "${BLUE}Coverage reporting enabled${NC}"
fi

# =============================================================================
# RUN TESTS
# =============================================================================

# Version compatibility check
echo -e "${GREEN}=== Checking Version Compatibility ===${NC}"
if ! uv run python "${SCRIPT_DIR}/check_version_compatibility.py"; then
    echo -e "${RED}Version compatibility check failed!${NC}"
    exit 1
fi
echo ""

echo -e "${GREEN}=== Running Tests ===${NC}"
set +e
TEST_EXIT_CODE=0

# Build pytest arguments
PYTEST_CMD_ARGS=()
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    PYTEST_CMD_ARGS+=("${TEST_DIR}/" "-v")
else
    PYTEST_CMD_ARGS+=("${PYTEST_ARGS[@]}")
fi

# Append e2e test file if --e2e flag was used and not already in args
if [ "$INCLUDE_E2E" = true ]; then
    if [[ ! " ${PYTEST_CMD_ARGS[*]} " =~ "test_e2e_avatar_feed" ]]; then
        PYTEST_CMD_ARGS+=("${TEST_DIR}/test_e2e_avatar_feed.py")
    fi
    echo -e "${BLUE}Including live e2e avatar feed test (requires OpenRouter key)${NC}"
fi

PYTEST_FULL_ARGS=("${PYTEST_CMD_ARGS[@]}")
if [ ${#COVERAGE_ARGS[@]} -gt 0 ]; then
    PYTEST_FULL_ARGS+=("${COVERAGE_ARGS[@]}")
fi

if [ "$USE_DOCKER" = true ]; then
    CONTAINER_NAME="gofr-iq-dev"
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${RED}Container ${CONTAINER_NAME} is not running.${NC}"
        exit 1
    fi
    
    DOCKER_PYTEST_ARGS=""
    for arg in "${PYTEST_FULL_ARGS[@]}"; do
        if [ -n "$DOCKER_PYTEST_ARGS" ]; then
            DOCKER_PYTEST_ARGS+=" "
        fi
        DOCKER_PYTEST_ARGS+="$(printf '%q' "$arg")"
    done

    docker exec "${CONTAINER_NAME}" bash -c "cd /home/gofr/devroot/${PROJECT_NAME} && source .venv/bin/activate && pytest ${DOCKER_PYTEST_ARGS}"
    TEST_EXIT_CODE=$?
else
    echo -e "${BLUE}Running full test suite...${NC}"
    uv run python -m pytest "${PYTEST_FULL_ARGS[@]}"
    TEST_EXIT_CODE=$?
fi
set -e

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
