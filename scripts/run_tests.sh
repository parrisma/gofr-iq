#!/bin/bash
# gofr-iq Test Runner
# Runs pytest with proper environment configuration

set -euo pipefail

# Colors for status output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Locate project root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Source centralized environment configuration in TEST mode
export GOFRIQ_ENV="TEST"
if [ -f "${SCRIPT_DIR}/gofriq.env" ]; then
    source "${SCRIPT_DIR}/gofriq.env"
fi

# Shared authentication configuration for tests
export GOFRIQ_JWT_SECRET="test-secret-key-for-secure-testing-do-not-use-in-production"
export GOFRIQ_TOKEN_STORE="${GOFRIQ_TOKEN_STORE:-${GOFRIQ_LOGS}/gofriq_tokens_test.json}"
export GOFRIQ_MCP_PORT="${GOFRIQ_MCP_PORT:-8060}"
export GOFRIQ_WEB_PORT="${GOFRIQ_WEB_PORT:-8062}"
export GOFRIQ_MCPO_PORT="${GOFRIQ_MCPO_PORT:-8061}"

# Use centralized paths from gofriq.env or fallback
TEST_DATA_ROOT="${GOFRIQ_DATA:-test/data}"
STORAGE_DIR="${GOFRIQ_STORAGE:-${TEST_DATA_ROOT}/storage}"

# Ensure directories exist
mkdir -p "${STORAGE_DIR}" "${GOFRIQ_LOGS}"

print_header() {
    echo -e "${GREEN}=== GOFR-IQ Test Runner ===${NC}"
    echo "Project root: ${PROJECT_ROOT}"
    echo "Environment: ${GOFRIQ_ENV:-NONE}"
    echo "JWT Secret: ${GOFRIQ_JWT_SECRET:0:20}..."
    echo "Token store: ${GOFRIQ_TOKEN_STORE}"
    echo "MCP Port: ${GOFRIQ_MCP_PORT}"
    echo "Web Port: ${GOFRIQ_WEB_PORT}"
    echo "MCPO Port: ${GOFRIQ_MCPO_PORT}"
    echo "Storage Dir: ${STORAGE_DIR}"
    echo
}

cleanup_environment() {
    echo -e "${YELLOW}Cleaning up test environment...${NC}"
    
    # Empty token store (create empty JSON object)
    echo "{}" > "${GOFRIQ_TOKEN_STORE}" 2>/dev/null || true
    echo "Token store emptied: ${GOFRIQ_TOKEN_STORE}"
    
    echo -e "${GREEN}Cleanup complete${NC}\n"
}

print_header

CLEANUP_ONLY=false
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options] [pytest args]"
            echo ""
            echo "Options:"
            echo "  --cleanup-only    Only clean up test environment, don't run tests"
            echo "  --help, -h        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                      Run all tests"
            echo "  $0 -v                   Run all tests with verbose output"
            echo "  $0 test/test_hello.py   Run specific test file"
            echo "  $0 -k test_config       Run tests matching pattern"
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

if [ "$CLEANUP_ONLY" = true ]; then
    cleanup_environment
    exit 0
fi

cleanup_environment

# Seed default token store if missing
if [ ! -f "${GOFRIQ_TOKEN_STORE}" ]; then
    echo -e "${BLUE}Seeding bootstrap token store...${NC}"
    echo "{}" > "${GOFRIQ_TOKEN_STORE}"
fi

echo -e "${GREEN}=== Running Tests ===${NC}"
set +e
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    uv run python -m pytest test/ -v
else
    uv run python -m pytest "${PYTEST_ARGS[@]}"
fi
TEST_EXIT_CODE=$?
set -e

# Clean up token store after tests
echo -e "${YELLOW}Cleaning up token store...${NC}"
echo "{}" > "${GOFRIQ_TOKEN_STORE}" 2>/dev/null || true
echo "Token store emptied"

echo
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}=== Tests Passed ===${NC}"
else
    echo -e "${RED}=== Tests Failed (exit code: ${TEST_EXIT_CODE}) ===${NC}"
fi

exit $TEST_EXIT_CODE
