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
#   ./scripts/run_tests.sh --mode unit              # Fast, no deps (default for LLMs)
#   ./scripts/run_tests.sh --mode all               # Full suite (requires key in .env)
#   
#   Common options:
#   --mode mode_name      : Execution mode (unit|integration|all).
#                           - unit: Fast, mocks only, no containers needed.
#                           - integration: Spin up servers/DBs. Needs 4GB+ RAM.
#                           - all: Everything.
#
#   --refresh-env         : Reset test secrets/tokens/ports. Use if 401/403 errors.
#   --stop                : Stop orphaned test servers. Use before retrying.
#   --cleanup-only        : aggressive cleanup of containers/networks.
#
#   LLM/Agent Instructions:
#   - Prefer `--mode unit` for quick code verification.
#   - Use `--mode all` ONLY if you have verified `GOFR_IQ_OPENROUTER_API_KEY` in .env.
#   - If integration tests fail with 401s, run with `--refresh-env`.
#   - If ports conflict, run with `--stop` then try again.
# =============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# =============================================================================
# CONFIGURATION & ENVIRONMENT STRATEGY
# =============================================================================
# LLM Note: This script enforces a "Single Source of Truth" pattern.
# - Secrets are loaded ONLY from lib/gofr-common/.env
# - Generated tokens are stored in tokens.env (gitignored)
# - Do NOT create local .env files in app/ or test/ subdirs; they will be ignored/overwritten.
#

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
CONTAINER_NAME="gofr-iq-dev"
TEST_DIR="test"
COVERAGE_SOURCE="app"
LOG_DIR="${PROJECT_ROOT}/logs"
TEST_ENV_SCRIPT="${SCRIPT_DIR}/test_env.sh"
TEST_SERVERS_SCRIPT="${SCRIPT_DIR}/test_servers.sh"
SECRETS_ENV_FILE="${PROJECT_ROOT}/config/generated/secrets.env"
DOCKER_ENV_FILE="${PROJECT_ROOT}/docker/.env"
REQUIRED_ENV_FILES=("${SECRETS_ENV_FILE}" "${DOCKER_ENV_FILE}")

# Default execution settings (will be refined after parsing CLI args)
MODE="unit"
USE_DOCKER=false
COVERAGE=false
COVERAGE_HTML=false
START_SERVERS=true
STOP_ONLY=false
CLEANUP_ONLY=false
REBUILD_IMAGES=false
PYTEST_ARGS=()
NEEDS_ENV_SETUP=false
UNIT_MODE=false
TEST_ENV_STARTED=false
TEST_SERVERS_STARTED=false
REFRESH_ENV=false
FORCE_CLEANUP=false
CLEANUP_IN_PROGRESS=false

# Activate virtual environment
VENV_DIR="${PROJECT_ROOT}/.venv"
if [ -f "${VENV_DIR}/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    echo "Activated venv: ${VENV_DIR}"
else
    echo -e "${YELLOW}Warning: Virtual environment not found at ${VENV_DIR}${NC}"
fi

# =============================================================================
# ARGUMENT PARSING (early so mode can influence setup work)
# =============================================================================

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            if [[ -z "${2:-}" ]]; then
                echo -e "${RED}ERROR:${NC} --mode requires a value (unit|integration|all)" >&2
                exit 1
            fi
            MODE="$(echo "${2}" | tr '[:upper:]' '[:lower:]')"
            shift 2
            ;;
        --mode=*)
            MODE="$(echo "${1#--mode=}" | tr '[:upper:]' '[:lower:]')"
            shift
            ;;
        --unit|--integration|--all)
            echo -e "${RED}ERROR:${NC} '$1' has been removed. Use --mode unit|integration|all." >&2
            exit 1
            ;;
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
        --refresh-env)
            REFRESH_ENV=true
            shift
            ;;
        --no-servers|--without-servers|--with-servers|--start-servers)
            echo -e "${RED}ERROR:${NC} '$1' has been removed. Select a mode instead (unit skips servers, integration/all start them)." >&2
            exit 1
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
            echo "  --mode unit|integration|all  Select execution profile (default: unit)"
            echo "  --docker                     Run tests inside the dev container"
            echo "  --coverage                   Enable coverage (terminal report)"
            echo "  --coverage-html              Add HTML coverage report (implies --coverage)"
            echo "  --refresh-env                Regenerate docker/.env + secrets before tests"
            echo "  --rebuild                    Rebuild Docker images before integration tests"
            echo "  --stop                       Stop servers and exit"
            echo "  --cleanup-only               Clean environment artifacts and exit"
            echo "  --help, -h                   Show this help message"
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

case "$MODE" in
    unit)
        UNIT_MODE=true
        DEFAULT_START_SERVERS=false
        ;;
    integration|all)
        UNIT_MODE=false
        DEFAULT_START_SERVERS=true
        ;;
    *)
        echo -e "${RED}ERROR:${NC} Unknown mode '${MODE}'. Use unit, integration, or all." >&2
        exit 1
        ;;
esac

ENV_SETUP_REASON=""
if [ "$REFRESH_ENV" = true ]; then
    NEEDS_ENV_SETUP=true
    ENV_SETUP_REASON="manual refresh requested"
elif [ "$UNIT_MODE" = false ]; then
    for env_file in "${REQUIRED_ENV_FILES[@]}"; do
        if [ ! -f "$env_file" ]; then
            NEEDS_ENV_SETUP=true
            ENV_SETUP_REASON="missing $(basename "$env_file")"
            break
        fi
    done
fi

START_SERVERS="$DEFAULT_START_SERVERS"

if [ "$UNIT_MODE" = true ]; then
    START_SERVERS=false
fi

# Running tests inside Docker skips host server lifecycle entirely
if [ "$USE_DOCKER" = true ]; then
    START_SERVERS=false
fi

if [ "$NEEDS_ENV_SETUP" = true ]; then
    setup_reason="${ENV_SETUP_REASON:-manual refresh}"
    echo "Refreshing test environment artifacts (${setup_reason})..."

    # Purge test data from previous runs
    echo "Purging test data..."
    "${SCRIPT_DIR}/purge_local_data.sh" --test-only --force

    # =============================================================================
    # ENVIRONMENT SETUP (New Standard)
    # =============================================================================

    # Generate ephemeral test environment configuration
    # This creates config/generated/secrets.env and docker/.env
    echo "Generating test environment configuration..."
    export GOFR_VAULT_DEV_TOKEN="${GOFR_VAULT_DEV_TOKEN:-gofr-dev-root-token}"
    export GOFR_JWT_SECRET="${GOFR_JWT_SECRET:-test-jwt-secret-$(date +%s)}"

    # Use generate_envs.sh if available (preferred)
    if [ -f "${SCRIPT_DIR}/generate_envs.sh" ]; then
        "${SCRIPT_DIR}/generate_envs.sh" --mode test
    elif [ -f "${PROJECT_ROOT}/lib/gofr-common/scripts/generate_envs.sh" ]; then
        "${PROJECT_ROOT}/lib/gofr-common/scripts/generate_envs.sh" --mode test
    fi
elif [ "$UNIT_MODE" = false ]; then
    echo "Reusing existing generated env artifacts (pass --refresh-env to regenerate)"
fi

if [ -f "${SECRETS_ENV_FILE}" ]; then
    # Always source the generated secrets if present (even when reusing)
    # shellcheck disable=SC1090
    source "${SECRETS_ENV_FILE}"
fi

# =============================================================================
# TEST CONFIGURATION (shared)
# =============================================================================
# IMPORTANT: Configuration loaded from .env files (single source of truth)
# - Ports: GOFR_IQ_*_PORT loaded from gofr_ports.env (integration/all modes)
# - Secrets: GOFR_JWT_SECRET, GOFR_VAULT_DEV_TOKEN from .env or defaults
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
    # shellcheck disable=SC1090
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
    # shellcheck disable=SC1090
    source "${GOFR_COMMON_ENV}"
    set +a
    echo "Loaded secrets from gofr-common/.env"
fi

if [ -z "${GOFR_VAULT_DEV_TOKEN:-}" ]; then
    export GOFR_VAULT_DEV_TOKEN="gofr-dev-root-token"
fi

# JWT Secret: Required for auth - should come from .env
if [ -z "${GOFR_JWT_SECRET:-}" ]; then
    echo -e "${YELLOW}Warning: GOFR_JWT_SECRET not set, generating test secret${NC}"
    generated_jwt_secret="test-jwt-secret-$(date +%s)"
    export GOFR_JWT_SECRET="${generated_jwt_secret}"
fi
echo "  JWT Secret: ${GOFR_JWT_SECRET:0:20}..."

# OpenRouter API Key: Required for LLM integration tests
if [ -z "${GOFR_IQ_OPENROUTER_API_KEY:-}" ]; then
    echo -e "${YELLOW}Warning: GOFR_IQ_OPENROUTER_API_KEY not set in lib/gofr-common/.env${NC}"
    echo "  LLM integration tests will be skipped. To enable them:"
    echo "  1. Get an API key from https://openrouter.ai/"
    echo "  2. Add it to lib/gofr-common/.env: GOFR_IQ_OPENROUTER_API_KEY=sk-or-v1-..."
else
    export GOFR_IQ_OPENROUTER_API_KEY
    echo "  OpenRouter API Key: ${GOFR_IQ_OPENROUTER_API_KEY:0:15}...${GOFR_IQ_OPENROUTER_API_KEY: -4}"
fi

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
# Also set VAULT_ADDR and VAULT_TOKEN for gofr_env.py compatibility
export VAULT_ADDR="http://gofr-vault-test:8200"
export VAULT_TOKEN="${GOFR_VAULT_DEV_TOKEN}"

# Source centralized environment configuration (won't override already-set vars)
if [ -f "${SCRIPT_DIR}/gofr-iq.env" ]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/gofr-iq.env"
elif [ -f "${SCRIPT_DIR}/gofriq.env" ]; then
    # Legacy support
    # shellcheck disable=SC1091
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
export GOFR_NEO4J_HTTP_PORT_CONTAINER="7474"

# JWT Secret: Use GOFR_JWT_SECRET from gofr_ports.sh as THE single source of truth
# Legacy alias for backward compatibility with code that uses GOFR_IQ_JWT_SECRET
export GOFR_IQ_JWT_SECRET="${GOFR_JWT_SECRET}"
export GOFR_IQ_MCP_PORT="${GOFR_IQ_MCP_PORT}"
export GOFR_IQ_WEB_PORT="${GOFR_IQ_WEB_PORT}"

# Ensure directories exist
mkdir -p "${LOG_DIR}"
mkdir -p "${GOFR_IQ_STORAGE:-${PROJECT_ROOT}/data/storage}"

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

stop_servers() {
    echo "Stopping server processes..."
    run_test_servers_cmd stop || true

    local patterns=(
        "app/main_mcp\.py"
        "app/main_web\.py"
        "app/main_mcpo\.py"
        "mcpo.*--port.*${GOFR_IQ_MCPO_PORT}"
    )

    for pattern in "${patterns[@]}"; do
        pkill -f "$pattern" 2>/dev/null || true
    done

    sleep 1

    if pgrep -f "app/main_(mcp|web|mcpo)\.py" >/dev/null 2>&1; then
        echo -e "${YELLOW}WARNING: Some server processes may still be running${NC}"
        pgrep -af "app/main_(mcp|web|mcpo)\.py" 2>/dev/null || true
    else
        echo "All server processes stopped"
    fi
}

# =============================================================================
# CLEANUP STRATEGY
# LLM Note:
# - This function attempts to kill any process matching the server patterns.
# - It is called on EXIT/INT/TERM via trap.
# - If you see "Address already in use" errors during server spin-up, it means
#   this cleanup failed or a previous run crashed hard.
# - Use `--cleanup-only` to manually trigger this if you are stuck.
# =============================================================================
cleanup_environment() {
    local exit_code=$?
    if [ "$CLEANUP_IN_PROGRESS" = true ]; then
        return $exit_code
    fi
    CLEANUP_IN_PROGRESS=true

    if [ "$FORCE_CLEANUP" = true ] || [ "$TEST_SERVERS_STARTED" = true ]; then
        stop_servers || true
    fi

    if [ "$FORCE_CLEANUP" = true ] || [ "$TEST_ENV_STARTED" = true ]; then
        echo "Stopping test infrastructure..."
        run_test_env_cmd stop || true
    fi

    # Clean up orphaned/dangling Docker volumes left by tests
    echo "Checking for orphaned Docker volumes..."
    local dangling_volumes
    dangling_volumes=$(docker volume ls -qf dangling=true 2>/dev/null || true)
    if [ -n "$dangling_volumes" ]; then
        echo "Removing $(echo "$dangling_volumes" | wc -l) dangling Docker volume(s)..."
        echo "$dangling_volumes" | xargs -r docker volume rm 2>/dev/null || true
    else
        echo "No dangling Docker volumes found"
    fi

    if [ -n "${GOFR_IQ_TOKEN_STORE:-}" ] && [ -f "${GOFR_IQ_TOKEN_STORE}" ]; then
        rm -f "${GOFR_IQ_TOKEN_STORE}" 2>/dev/null || true
    fi

    CLEANUP_IN_PROGRESS=false
    FORCE_CLEANUP=false
    return $exit_code
}

trap cleanup_environment EXIT INT TERM

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
    FORCE_CLEANUP=true
    cleanup_environment
    exit 0
fi

# Only ensure local servers are down for integration tests (unit tests never start them)
if [ "$UNIT_MODE" = true ]; then
    echo -e "${YELLOW}Unit test mode - skipping server cleanup${NC}"
elif [ "$USE_DOCKER" = false ]; then
    echo -e "${BLUE}Ensuring MCP/MCPO/Web servers are not already running...${NC}"
    stop_servers
fi

# Start servers if needed
if [ "$START_SERVERS" = true ] && [ "$USE_DOCKER" = false ]; then
    # Start test infrastructure via manage-infra.sh (Vault, ChromaDB, Neo4j)
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
    
    # ==========================================================================
    # MINI-BOOTSTRAP: Initialize Test Vault with JWT Secret
    # ==========================================================================
    # MCP server requires JWT secret to be in Vault. Write it before starting servers.
    echo -e "${BLUE}Initializing test Vault with JWT secret...${NC}"
    if curl -sf -X POST \
        -H "X-Vault-Token: ${VAULT_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"data\": {\"value\": \"${GOFR_JWT_SECRET}\"}}" \
        "${VAULT_ADDR}/v1/secret/data/gofr/config/jwt-signing-secret" >/dev/null 2>&1; then
        echo -e "${GREEN}  JWT secret stored in test Vault${NC}"
    else
        echo -e "${YELLOW}  Warning: Could not store JWT in Vault (may already exist or Vault unreachable)${NC}"
        echo "  MCP will fall back to CLI argument for JWT secret"
    fi
    
    # NOTE: Auth bootstrap (admin/public groups & tokens) happens in conftest.py
    # This ensures tokens are created with correct JWT secret after Vault is ready
    echo -e "${BLUE}Auth bootstrap will run in pytest session fixture (conftest.py)${NC}"
    echo ""
    
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

# Run version compatibility check first
echo -e "${GREEN}=== Checking Version Compatibility ===${NC}"
if ! uv run python "${SCRIPT_DIR}/check_version_compatibility.py"; then
    echo -e "${RED}Version compatibility check failed!${NC}"
    echo "Fix version mismatches before running tests."
    if [ "$START_SERVERS" = true ] && [ "$USE_DOCKER" = false ]; then
        run_test_env_cmd stop || true
    fi
    exit 1
fi
echo ""

echo -e "${GREEN}=== Running Tests ===${NC}"
set +e
TEST_EXIT_CODE=0

PYTEST_CMD_ARGS=()
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    PYTEST_CMD_ARGS+=("${TEST_DIR}/" "-v")
else
    PYTEST_CMD_ARGS+=("${PYTEST_ARGS[@]}")
fi

USER_DEFINED_MARKERS=false
for arg in "${PYTEST_ARGS[@]}"; do
    if [[ "$arg" == "-m" || "$arg" == "-m="* ]]; then
        USER_DEFINED_MARKERS=true
        break
    fi
done

MARKER_EXPR=""
case "$MODE" in
    unit)
        MARKER_EXPR="not integration and not e2e"
        ;;
    integration)
        MARKER_EXPR="integration"
        ;;
    all)
        MARKER_EXPR=""
        ;;
esac

MARKER_ARGS=()
if [ -n "$MARKER_EXPR" ] && [ "$USER_DEFINED_MARKERS" = false ]; then
    MARKER_ARGS=(-m "$MARKER_EXPR")
fi

PYTEST_FULL_ARGS=("${PYTEST_CMD_ARGS[@]}")
if [ ${#MARKER_ARGS[@]} -gt 0 ]; then
    PYTEST_FULL_ARGS+=("${MARKER_ARGS[@]}")
fi
if [ ${#COVERAGE_ARGS[@]} -gt 0 ]; then
    PYTEST_FULL_ARGS+=("${COVERAGE_ARGS[@]}")
fi

if [ "$USE_DOCKER" = true ]; then
    # Docker execution
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${RED}Container ${CONTAINER_NAME} is not running.${NC}"
        echo "Run: ./docker/run-dev.sh to create it"
        exit 1
    fi
    
    DOCKER_PYTEST_ARGS=""
    for arg in "${PYTEST_FULL_ARGS[@]}"; do
        if [ -n "$DOCKER_PYTEST_ARGS" ]; then
            DOCKER_PYTEST_ARGS+=" "
        fi
        DOCKER_PYTEST_ARGS+="$(printf '%q' "$arg")"
    done

    DOCKER_CMD="cd /home/gofr/devroot/${PROJECT_NAME} && source .venv/bin/activate && pytest ${DOCKER_PYTEST_ARGS}"
    docker exec "${CONTAINER_NAME}" bash -c "${DOCKER_CMD}"
    TEST_EXIT_CODE=$?
else
    case "$MODE" in
        unit)
            echo -e "${BLUE}Running unit tests only (no servers)...${NC}"
            ;;
        integration)
            echo -e "${BLUE}Running integration test suite...${NC}"
            ;;
        all)
            echo -e "${BLUE}Running full test suite...${NC}"
            ;;
    esac

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
