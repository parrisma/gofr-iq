#!/bin/bash
# gofr-iq Test Runner
# Runs pytest with proper environment configuration
# Optionally manages ephemeral test infrastructure (ChromaDB, Neo4j)

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
DOCKER_DIR="${PROJECT_ROOT}/docker"
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
# When running tests from host, connect to localhost mapped ports
export GOFRIQ_CHROMADB_HOST="${GOFRIQ_CHROMADB_HOST:-localhost}"
export GOFRIQ_CHROMADB_PORT="${GOFRIQ_CHROMADB_PORT:-8101}"

# Neo4j configuration for tests
export GOFRIQ_NEO4J_HOST="${GOFRIQ_NEO4J_HOST:-localhost}"
export GOFRIQ_NEO4J_BOLT_PORT="${GOFRIQ_NEO4J_BOLT_PORT:-7688}"
export GOFRIQ_NEO4J_HTTP_PORT="${GOFRIQ_NEO4J_HTTP_PORT:-7475}"
export GOFRIQ_NEO4J_PASSWORD="${GOFRIQ_NEO4J_PASSWORD:-testpassword}"

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
    
    if [ -n "${GOFR_IQ_OPENROUTER_API_KEY:-}" ]; then
        echo "OpenRouter Key: Set"
    else
        echo "OpenRouter Key: Not Set (LLM tests will skip)"
    fi
    echo
}

cleanup_environment() {
    echo -e "${YELLOW}Cleaning up test environment...${NC}"
    
    # Empty token store (create empty JSON object)
    echo "{}" > "${GOFRIQ_TOKEN_STORE}" 2>/dev/null || true
    echo "Token store emptied: ${GOFRIQ_TOKEN_STORE}"
    
    echo -e "${GREEN}Cleanup complete${NC}\n"
}

# Infrastructure management functions
verify_connectivity() {
    echo -e "${BLUE}Verifying connectivity to test infrastructure...${NC}"
    
    # Use internal container names and ports (since we connect to the network)
    local chroma_host="gofr-iq-chromadb-test"
    local chroma_port="8000"
    local neo4j_host="gofr-iq-neo4j-test"
    local neo4j_http_port="7474"
    local neo4j_bolt_port="7687"
    
    local chroma_url="http://${chroma_host}:${chroma_port}/api/v2/heartbeat"
    local neo4j_url="http://${neo4j_host}:${neo4j_http_port}"
    
    local max_retries=30
    local retry_count=0
    
    # Verify ChromaDB
    echo -n "Checking ChromaDB at ${chroma_url}..."
    while ! curl -s --fail "${chroma_url}" > /dev/null; do
        retry_count=$((retry_count + 1))
        if [ $retry_count -ge $max_retries ]; then
            echo -e "\n${RED}✗ Failed to connect to ChromaDB after ${max_retries} attempts${NC}"
            return 1
        fi
        sleep 1
        echo -n "."
    done
    echo -e " ${GREEN}OK${NC}"

    # Verify Neo4j HTTP
    retry_count=0
    echo -n "Checking Neo4j HTTP at ${neo4j_url}..."
    while ! curl -s "${neo4j_url}" > /dev/null; do
        retry_count=$((retry_count + 1))
        if [ $retry_count -ge $max_retries ]; then
            echo -e "\n${RED}✗ Failed to connect to Neo4j after ${max_retries} attempts${NC}"
            return 1
        fi
        sleep 1
        echo -n "."
    done
    echo -e " ${GREEN}OK${NC}"
    
    # Verify Neo4j database is ready (can execute queries)
    retry_count=0
    local db_max_retries=60
    echo -n "Waiting for Neo4j database to be ready..."
    while ! uv run python -c "
from neo4j import GraphDatabase
driver = GraphDatabase.driver('bolt://${neo4j_host}:${neo4j_bolt_port}', auth=('neo4j', 'testpassword'))
with driver.session() as session:
    session.run('RETURN 1')
driver.close()
" 2>/dev/null; do
        retry_count=$((retry_count + 1))
        if [ $retry_count -ge $db_max_retries ]; then
            echo -e "\n${RED}✗ Neo4j database not ready after ${db_max_retries} attempts${NC}"
            return 1
        fi
        sleep 2
        echo -n "."
    done
    echo -e " ${GREEN}OK${NC}"
    
    return 0
}

start_test_infra() {
    echo -e "${BLUE}Starting ephemeral test infrastructure...${NC}"
    
    # Check if docker compose is available
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Docker not available. Skipping infrastructure setup.${NC}"
        return 1
    fi
    
    cd "${DOCKER_DIR}"
    
    # Start test containers
    docker compose -f docker-compose.test.yml up -d --build
    
    # Connect this container to the test network so we can access containers by name
    echo -e "${BLUE}Connecting dev container to test network...${NC}"
    if docker network connect gofr-test-net $(hostname) 2>/dev/null; then
        echo "Connected to gofr-test-net"
    else
        echo "Already connected or failed to connect (ignoring)"
    fi
    
    # Wait for health checks
    echo -e "${YELLOW}Waiting for services to be healthy...${NC}"
    local max_wait=90
    local elapsed=0
    
    while [ $elapsed -lt $max_wait ]; do
        local chroma_health=$(docker inspect --format='{{.State.Health.Status}}' gofr-iq-chromadb-test 2>/dev/null || echo "starting")
        local neo4j_health=$(docker inspect --format='{{.State.Health.Status}}' gofr-iq-neo4j-test 2>/dev/null || echo "starting")
        
        if [ "$chroma_health" = "healthy" ] && [ "$neo4j_health" = "healthy" ]; then
            echo -e "${GREEN}Docker containers are healthy${NC}"
            
            # Verify actual connectivity from host
            if verify_connectivity; then
                # Update environment to point to test containers
                export GOFRIQ_CHROMADB_HOST="gofr-iq-chromadb-test"
                export GOFRIQ_CHROMADB_PORT="8000"
                export GOFRIQ_NEO4J_HOST="gofr-iq-neo4j-test"
                export GOFRIQ_NEO4J_BOLT_PORT="7687"
                export GOFRIQ_NEO4J_HTTP_PORT="7474"
                
                cd "${PROJECT_ROOT}"
                return 0
            else
                echo -e "${RED}Connectivity check failed${NC}"
                docker compose -f docker-compose.test.yml logs
                cd "${PROJECT_ROOT}"
                return 1
            fi
        fi
        
        sleep 2
        elapsed=$((elapsed + 2))
        printf "."
    done
    
    echo -e "\n${RED}Infrastructure did not become healthy in ${max_wait}s${NC}"
    docker compose -f docker-compose.test.yml logs
    cd "${PROJECT_ROOT}"
    return 1
}

stop_test_infra() {
    echo -e "${YELLOW}Stopping test infrastructure...${NC}"
    
    if command -v docker &> /dev/null; then
        cd "${DOCKER_DIR}"
        docker compose -f docker-compose.test.yml down -v 2>/dev/null || true
        cd "${PROJECT_ROOT}"
    fi
    
    echo -e "${GREEN}Test infrastructure stopped${NC}"
}

print_header

CLEANUP_ONLY=false
WITH_INFRA=true  # Default: start infrastructure for tests
NO_INFRA=false
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cleanup-only)
            CLEANUP_ONLY=true
            shift
            ;;
        --with-infra|--infra)
            WITH_INFRA=true
            shift
            ;;
        --no-infra)
            WITH_INFRA=false
            NO_INFRA=true
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
                10a|mcp-server|mcp-integration)
                    # MCP server integration tests (starts actual server)
                    PYTEST_ARGS+=("test/test_mcp_server_integration.py" "-v" "-m" "integration")
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
                    PYTEST_ARGS+=("-m" "integration" "-v")
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
            echo "  --with-infra          Start ephemeral ChromaDB/Neo4j containers (DEFAULT)"
            echo "  --no-infra            Skip infrastructure startup (faster, uses existing)"
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
            echo "  10  - Basic MCP tools (unit tests)"
            echo "  10a - MCP server integration (starts real server)"
            echo "  11 - Audit logging"
            echo "  12 - ChromaDB integration"
            echo "  13 - Neo4j integration"
            echo "  14 - Query service (hybrid search)"
            echo "  15 - Web API"
            echo "  16 - Index rebuild & admin tools"
            echo "  17 - All integration tests"
            echo "  18 - Elasticsearch (optional)"
            echo ""
            echo "Examples:"
            echo "  $0                          Run all tests"
            echo "  $0 --with-infra             Run all tests with ephemeral containers"
            echo "  $0 --phase 0                Run Phase 0 (infrastructure) tests"
            echo "  $0 --phase infrastructure   Same as --phase 0"
            echo "  $0 --phase mcp-server       Run MCP server integration tests"
            echo "  $0 -f test/test_hello.py    Run specific test file"
            echo "  $0 -k test_config           Run tests matching pattern"
            echo "  $0 -q                       Quick run (no integration tests)"
            echo "  $0 -v --tb=short            Pass args directly to pytest"
            echo "  $0 --cleanup-only --with-infra  Clean up and stop test containers"
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
    if [ "$WITH_INFRA" = true ]; then
        stop_test_infra
    fi
    exit 0
fi

# Set up trap to clean up infrastructure on exit
if [ "$WITH_INFRA" = true ]; then
    trap 'stop_test_infra' EXIT
fi

cleanup_environment

# Start test infrastructure if requested
if [ "$WITH_INFRA" = true ]; then
    if ! start_test_infra; then
        echo -e "${RED}Failed to start test infrastructure. Aborting.${NC}"
        exit 1
    fi
fi

# Seed default token store if missing
if [ ! -f "${GOFRIQ_TOKEN_STORE}" ]; then
    echo -e "${BLUE}Seeding bootstrap token store...${NC}"
    echo "{}" > "${GOFRIQ_TOKEN_STORE}"
fi

echo -e "${GREEN}=== Running Code Quality Tests First ===${NC}"
set +e
uv run python -m pytest test/code_quality/ -v
CODE_QUALITY_EXIT_CODE=$?
set -e

if [ $CODE_QUALITY_EXIT_CODE -ne 0 ]; then
    echo
    echo -e "${RED}=== Code Quality Tests Failed ===${NC}"
    echo -e "${RED}Fix linting and type errors before running other tests.${NC}"
    
    # Clean up token store
    echo -e "${YELLOW}Cleaning up token store...${NC}"
    echo "{}" > "${GOFRIQ_TOKEN_STORE}" 2>/dev/null || true
    echo "Token store emptied"
    
    exit $CODE_QUALITY_EXIT_CODE
fi

echo -e "${GREEN}✓ Code Quality Tests Passed${NC}"
echo

echo -e "${GREEN}=== Running Remaining Tests ===${NC}"
set +e
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    # Run with coverage reporting
    uv run python -m pytest test/ -v --ignore=test/code_quality/ --cov=app --cov-report=term-missing --cov-report=xml
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
