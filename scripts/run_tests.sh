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

# ChromaDB configuration for tests
# Use 'gofr-iq-chromadb' hostname when running in Docker network, localhost otherwise
export GOFRIQ_CHROMADB_HOST="${GOFRIQ_CHROMADB_HOST:-gofr-iq-chromadb}"
export GOFRIQ_CHROMADB_PORT="${GOFRIQ_CHROMADB_PORT:-8000}"

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
    echo "ChromaDB: ${GOFRIQ_CHROMADB_HOST}:${GOFRIQ_CHROMADB_PORT}"
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
        --phase)
            # Run tests for a specific implementation phase
            # Maps phase numbers to test files/patterns
            PHASE="$2"
            case "$PHASE" in
                0|infrastructure)
                    PYTEST_ARGS+=("test/test_infrastructure.py" "-v")
                    ;;
                1|models)
                    PYTEST_ARGS+=("test/test_models.py" "-v")
                    ;;
                2|group-registry)
                    PYTEST_ARGS+=("-k" "group_registry or test_group" "-v")
                    ;;
                3|document-store)
                    PYTEST_ARGS+=("-k" "document_store or test_document" "-v")
                    ;;
                4|source-registry)
                    PYTEST_ARGS+=("-k" "source_registry or test_source" "-v")
                    ;;
                5|access-control)
                    PYTEST_ARGS+=("-k" "access_control or test_access" "-v")
                    ;;
                6|language)
                    PYTEST_ARGS+=("-k" "language" "-v")
                    ;;
                7|duplicate)
                    PYTEST_ARGS+=("-k" "duplicate" "-v")
                    ;;
                8|llm|extraction)
                    PYTEST_ARGS+=("-k" "llm or extraction" "-v")
                    ;;
                9|ingest)
                    PYTEST_ARGS+=("-k" "ingest" "-v")
                    ;;
                10|mcp)
                    PYTEST_ARGS+=("-k" "mcp" "-v")
                    ;;
                11|audit)
                    PYTEST_ARGS+=("-k" "audit" "-v")
                    ;;
                12|chroma)
                    PYTEST_ARGS+=("-k" "chroma" "-v")
                    ;;
                13|neo4j)
                    PYTEST_ARGS+=("-k" "neo4j" "-v")
                    ;;
                14|query)
                    PYTEST_ARGS+=("-k" "query" "-v")
                    ;;
                15|web)
                    PYTEST_ARGS+=("-k" "web" "-v")
                    ;;
                16|admin)
                    PYTEST_ARGS+=("-k" "admin or rebuild" "-v")
                    ;;
                17|docker|integration)
                    PYTEST_ARGS+=("-k" "integration or docker" "-v")
                    ;;
                18|elastic)
                    PYTEST_ARGS+=("-k" "elastic" "-v")
                    ;;
                *)
                    echo -e "${RED}Unknown phase: $PHASE${NC}"
                    echo "Valid phases: 0-18, infrastructure, models, group-registry, etc."
                    exit 1
                    ;;
            esac
            shift 2
            ;;
        --file|-f)
            # Run a specific test file
            PYTEST_ARGS+=("$2" "-v")
            shift 2
            ;;
        --pattern|-k)
            # Run tests matching a pattern
            PYTEST_ARGS+=("-k" "$2" "-v")
            shift 2
            ;;
        --quick|-q)
            # Quick run - only fast tests (exclude integration)
            PYTEST_ARGS+=("-m" "not integration" "-v")
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options] [pytest args]"
            echo ""
            echo "Options:"
            echo "  --cleanup-only        Only clean up test environment, don't run tests"
            echo "  --phase <N>           Run tests for implementation phase N (0-18)"
            echo "  --file, -f <file>     Run a specific test file"
            echo "  --pattern, -k <pat>   Run tests matching pattern"
            echo "  --quick, -q           Run only fast tests (exclude integration)"
            echo "  --help, -h            Show this help message"
            echo ""
            echo "Implementation Phases:"
            echo "  0  - Test infrastructure (TestDataStore, fixtures)"
            echo "  1  - Pydantic models (Group, Source, Document, Query)"
            echo "  2  - Group registry"
            echo "  3  - Canonical document store"
            echo "  4  - Source registry"
            echo "  5  - Group access control"
            echo "  6  - Language detection"
            echo "  7  - Duplicate detection"
            echo "  8  - LLM extraction service"
            echo "  9  - Basic ingest service"
            echo "  10 - Basic MCP tools"
            echo "  11 - Audit logging"
            echo "  12 - ChromaDB integration"
            echo "  13 - Neo4j integration"
            echo "  14 - Query service (hybrid search)"
            echo "  15 - Web API"
            echo "  16 - Index rebuild & admin tools"
            echo "  17 - Docker & integration"
            echo "  18 - Elasticsearch (optional)"
            echo ""
            echo "Examples:"
            echo "  $0                          Run all tests"
            echo "  $0 --phase 0                Run Phase 0 (infrastructure) tests"
            echo "  $0 --phase infrastructure   Same as --phase 0"
            echo "  $0 -f test/test_hello.py    Run specific test file"
            echo "  $0 -k test_config           Run tests matching pattern"
            echo "  $0 -q                       Quick run (no integration tests)"
            echo "  $0 -v --tb=short            Pass args directly to pytest"
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
