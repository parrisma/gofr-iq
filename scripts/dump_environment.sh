#!/bin/bash
# =============================================================================
# GOFR-IQ Environment Dump Script
# =============================================================================
# Dumps the complete environment state including:
# - Settings (ports, URIs, secrets)
# - Auth groups and tokens
# - Sources
# - Documents count
# - Infrastructure status
#
# Usage:
#   ./scripts/dump_environment.sh [OPTIONS]
#
# Options:
#   --docker, --prod     Use production docker environment (default)
#   --dev, --test        Use development/test environment
#   --secrets            Show full secrets (default: partially obscured)
#   --help, -h           Show this help message
# =============================================================================

set -euo pipefail

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Default options
ENV_MODE="prod"
OUTPUT_FORMAT="human"
SHOW_FULL_SECRETS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker|--prod)
            ENV_MODE="prod"
            shift
            ;;
        --dev|--test)
            ENV_MODE="dev"
            shift
            ;;
        --secrets)
            SHOW_FULL_SECRETS=true
            shift
            ;;
        --help|-h)
            cat << 'EOF'
GOFR-IQ Environment Dump Script

Usage:
  ./scripts/dump_environment.sh [OPTIONS]

Options:
    --docker, --prod     Use production docker environment (default)
    --dev, --test        Use development/test environment
    --secrets            Show full secrets (default: partially obscured)
    --help, -h           Show this help message

Examples:
  # Dump production environment
  ./scripts/dump_environment.sh --docker

  # Dump test environment
  ./scripts/dump_environment.sh --dev

  # Show full secrets
  ./scripts/dump_environment.sh --secrets
EOF
            exit 0
            ;;
        *)
            echo -e "${RED}ERROR:${NC} Unknown option: $1" >&2
            echo "Use --help for usage information" >&2
            exit 1
            ;;
    esac
done

# Load configuration
GOFR_PORTS_ENV="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
if [[ -f "${GOFR_PORTS_ENV}" ]]; then
    set -a
    source "${GOFR_PORTS_ENV}"
    set +a
fi

# Load docker/.env if exists
DOCKER_ENV="${PROJECT_ROOT}/docker/.env"
if [[ -f "${DOCKER_ENV}" ]]; then
    set -a
    source "${DOCKER_ENV}"
    set +a
fi

# Load lib/gofr-common/.env for secrets (OpenRouter API key, etc.)
COMMON_ENV="${PROJECT_ROOT}/lib/gofr-common/.env"
if [[ -f "${COMMON_ENV}" ]]; then
    set -a
    source "${COMMON_ENV}"
    set +a
fi

# Provide safe defaults for ports/hosts to avoid set -u aborts
GOFR_IQ_MCP_PORT=${GOFR_IQ_MCP_PORT:-8080}
GOFR_IQ_MCPO_PORT=${GOFR_IQ_MCPO_PORT:-8081}
GOFR_IQ_WEB_PORT=${GOFR_IQ_WEB_PORT:-8082}
GOFR_VAULT_PORT=${GOFR_VAULT_PORT:-8201}
GOFR_CHROMA_PORT=${GOFR_CHROMA_PORT:-8000}
GOFR_IQ_NEO4J_HTTP_PORT=${GOFR_IQ_NEO4J_HTTP_PORT:-7474}
GOFR_IQ_NEO4J_BOLT_PORT=${GOFR_IQ_NEO4J_BOLT_PORT:-7687}

# Load secrets if available
SECRETS_DIR="${PROJECT_ROOT}/secrets"
if [[ -f "${SECRETS_DIR}/vault_root_token" ]]; then
    VAULT_TOKEN=$(cat "${SECRETS_DIR}/vault_root_token")
    export VAULT_TOKEN
fi

# Activate virtual environment if available
VENV_DIR="${PROJECT_ROOT}/.venv"
if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
fi

# Set PYTHONPATH for gofr-common
if [[ -d "${PROJECT_ROOT}/lib/gofr-common/src" ]]; then
    export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/lib/gofr-common/src:${PYTHONPATH:-}"
elif [[ -d "${PROJECT_ROOT}/../gofr-common/src" ]]; then
    export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/../gofr-common/src:${PYTHONPATH:-}"
else
    export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
fi

# Set environment-specific variables
if [[ "${ENV_MODE}" == "prod" ]]; then
    MCP_HOST="gofr-iq-mcp"
    MCP_PORT="${GOFR_IQ_MCP_PORT}"
    VAULT_URL="http://gofr-vault:${GOFR_VAULT_PORT}"
else
    MCP_HOST="localhost"
    MCP_PORT="${GOFR_IQ_MCP_PORT_TEST:-$((GOFR_IQ_MCP_PORT + 100))}"
    VAULT_URL="http://localhost:${GOFR_VAULT_PORT_TEST:-$((GOFR_VAULT_PORT + 100))}"
fi

export GOFR_VAULT_URL="${VAULT_URL}"
export GOFR_AUTH_BACKEND="${GOFR_AUTH_BACKEND:-vault}"

# Helper functions
obscure_secret() {
    local secret="$1"
    local show_full="${2:-false}"
    
    if [[ "${show_full}" == "true" ]]; then
        echo "$secret"
    elif [[ -z "$secret" ]]; then
        echo "(not set)"
    elif [[ ${#secret} -le 10 ]]; then
        echo "${secret:0:3}...${secret: -1}"
    else
        echo "${secret:0:10}...${secret: -4}"
    fi
}

print_section() {
    local title="$1"
    local source="${2:-}"
    echo ""
    echo -e "${BOLD}${CYAN}=== $title ===${NC}"
    if [[ -n "$source" ]]; then
        echo -e "${YELLOW}    Source: ${source}${NC}"
    fi
    echo ""
}

print_key_value() {
    local key="$1"
    local value="$2"
    printf "  %-30s %s\n" "$key:" "$value"
}

check_service() {
    local service_name="$1"
    local host="$2"
    local port="$3"
    
    if timeout 2 bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
        echo -e "${GREEN}✓ Running${NC}"
    else
        echo -e "${RED}✗ Not available${NC}"
    fi
}

# Read a value from Vault with short timeouts
vault_read() {
    local secret_path="$1"
    curl -sf --max-time 3 --connect-timeout 2 -H "X-Vault-Token: ${VAULT_TOKEN}" \
        "${VAULT_URL}/v1/${secret_path}" 2>/dev/null
}

# =============================================================================
# COLLECT DATA
# =============================================================================

# 0. SETTINGS & CONFIGURATION
print_section "Environment Settings" "CLI args, script variables"

print_key_value "Environment Mode" "${ENV_MODE}"
print_key_value "Project Root" "${PROJECT_ROOT}"
print_key_value "Output Format" "${OUTPUT_FORMAT}"

print_section "Service Ports & URIs" "lib/gofr-common/config/gofr_ports.env, docker/.env"

print_key_value "MCP Server" "${MCP_HOST}:${MCP_PORT} ($(check_service 'MCP' "${MCP_HOST}" "${MCP_PORT}"))"
print_key_value "MCPO Server" "${GOFR_IQ_MCPO_PORT}"
print_key_value "Web Server" "${GOFR_IQ_WEB_PORT}"
print_key_value "Vault" "${VAULT_URL}"
print_key_value "ChromaDB" "${GOFR_IQ_CHROMADB_HOST:-localhost}:${GOFR_CHROMA_PORT}"
print_key_value "Neo4j HTTP" "${GOFR_IQ_NEO4J_HOST:-localhost}:${GOFR_NEO4J_HTTP_PORT}"
print_key_value "Neo4j Bolt" "bolt://${GOFR_IQ_NEO4J_HOST:-localhost}:${GOFR_NEO4J_BOLT_PORT}"

print_section "Service Connection Strings" "derived from ports/env"

# External (host) endpoints
print_key_value "MCP RPC (host)" "http://localhost:${MCP_PORT}"
print_key_value "MCPO OpenWebUI" "http://localhost:${GOFR_IQ_MCPO_PORT}"
print_key_value "Web UI" "http://localhost:${GOFR_IQ_WEB_PORT}"

# MCP integrations
print_key_value "MCP OpenRouter" "${GOFR_IQ_OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}"
print_key_value "MCP n8n" "http://localhost:${MCP_PORT}"

print_section "Secrets (Partially Obscured)" "Vault API, secrets/vault_root_token, lib/gofr-common/.env"

# Try to get secrets from Vault if not in env
if [[ -n "${VAULT_TOKEN:-}" ]]; then
    # JWT Secret
    if [[ -z "${GOFR_JWT_SECRET:-}" ]]; then
        GOFR_JWT_SECRET=$(vault_read "secret/data/gofr/config/jwt-signing-secret" | \
            python3 -c "import sys, json; data=json.load(sys.stdin); print(data['data']['data']['value'])" 2>/dev/null || echo "")
        export GOFR_JWT_SECRET
    fi
    
    # Neo4j Password
    if [[ -z "${NEO4J_PASSWORD:-}" ]]; then
        NEO4J_PASSWORD=$(vault_read "secret/data/gofr/config/neo4j-password" | \
            python3 -c "import sys, json; data=json.load(sys.stdin); print(data['data']['data']['value'])" 2>/dev/null || echo "")
        export NEO4J_PASSWORD
    fi
fi

print_key_value "JWT Secret" "$(obscure_secret "${GOFR_JWT_SECRET:-}" "$SHOW_FULL_SECRETS")"
print_key_value "Vault Token" "$(obscure_secret "${VAULT_TOKEN:-}" "$SHOW_FULL_SECRETS")"
print_key_value "OpenRouter API Key" "$(obscure_secret "${GOFR_IQ_OPENROUTER_API_KEY:-}" "$SHOW_FULL_SECRETS")"
print_key_value "Neo4j Password" "$(obscure_secret "${NEO4J_PASSWORD:-}" "$SHOW_FULL_SECRETS")"

print_section "LLM Configuration" "docker/.env (GOFR_IQ_LLM_MODEL, GOFR_IQ_EMBEDDING_MODEL)"

print_key_value "Chat Model" "${GOFR_IQ_LLM_MODEL:-anthropic/claude-opus-4}"
print_key_value "Embedding Model" "${GOFR_IQ_EMBEDDING_MODEL:-qwen/qwen3-embedding-8b}"
print_key_value "OpenRouter Base URL" "${GOFR_IQ_OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}"

# 1. AUTH GROUPS
print_section "Auth Groups" "lib/gofr-common/scripts/auth_manager.py groups list"

if [[ -n "${VAULT_TOKEN:-}" ]] && command -v python3 >/dev/null 2>&1; then
    # Ensure auth_manager.py has all required environment variables
    export VAULT_ADDR="${VAULT_URL}"
    export VAULT_TOKEN
    export GOFR_VAULT_TOKEN="${VAULT_TOKEN}"  # auth_manager.py expects this
    export GOFR_AUTH_BACKEND
    export GOFR_VAULT_URL="${VAULT_URL}"
    
    GROUPS_OUTPUT=$(python3 "${PROJECT_ROOT}/lib/gofr-common/scripts/auth_manager.py" groups list 2>&1 || echo "ERROR")
    if [[ "$GROUPS_OUTPUT" == "ERROR" ]] || [[ "$GROUPS_OUTPUT" == *"ERROR:"* ]]; then
        echo -e "${YELLOW}  Unable to retrieve groups${NC}"
        if [[ "$GROUPS_OUTPUT" != "ERROR" ]]; then
            echo -e "${YELLOW}  $GROUPS_OUTPUT${NC}"
        fi
    else
        echo "$GROUPS_OUTPUT"
    fi
else
    echo -e "${YELLOW}  Unable to retrieve groups (missing Vault token or Python)${NC}"
fi

# 2. AUTH TOKENS
print_section "Auth Tokens" "lib/gofr-common/scripts/auth_manager.py tokens list"

if [[ -n "${VAULT_TOKEN:-}" ]] && command -v python3 >/dev/null 2>&1; then
    export GOFR_VAULT_TOKEN="${VAULT_TOKEN}"
    TOKENS_OUTPUT=$(python3 "${PROJECT_ROOT}/lib/gofr-common/scripts/auth_manager.py" tokens list 2>&1 || echo "ERROR")
    if [[ "$TOKENS_OUTPUT" == "ERROR" ]] || [[ "$TOKENS_OUTPUT" == *"ERROR:"* ]]; then
        echo -e "${YELLOW}  Unable to retrieve tokens${NC}"
        if [[ "$TOKENS_OUTPUT" != "ERROR" ]]; then
            echo -e "${YELLOW}  $TOKENS_OUTPUT${NC}"
        fi
    else
        echo "$TOKENS_OUTPUT"
    fi
else
    echo -e "${YELLOW}  Unable to retrieve tokens (missing Vault token or Python)${NC}"
fi

# Get admin token for subsequent queries
ADMIN_TOKEN=""
if [[ -f "${PROJECT_ROOT}/secrets/bootstrap_tokens.json" ]]; then
    if command -v jq >/dev/null 2>&1; then
        ADMIN_TOKEN=$(jq -r '.admin_token // empty' "${PROJECT_ROOT}/secrets/bootstrap_tokens.json" 2>/dev/null || true)
    elif command -v python3 >/dev/null 2>&1; then
        ADMIN_TOKEN=$(python3 -c "import json; print(json.load(open('${PROJECT_ROOT}/secrets/bootstrap_tokens.json')).get('admin_token', ''))" 2>/dev/null || true)
    fi
fi

# Fallback to env vars
if [[ -z "$ADMIN_TOKEN" ]]; then
    ADMIN_TOKEN="${GOFR_IQ_ADMIN_TOKEN:-}"
fi

# Resolve data directory once for reuse
DATA_DIR="${PROJECT_ROOT}/data"
if [[ "${ENV_MODE}" == "dev" ]]; then
    DATA_DIR="${PROJECT_ROOT}/test/data"
fi

# 3. SOURCES
print_section "Sources" "scripts/manage_source.sh list"

if [[ -n "$ADMIN_TOKEN" ]]; then
    SOURCE_MODE_FLAG="--docker"
    if [[ "${ENV_MODE}" == "dev" ]]; then
        SOURCE_MODE_FLAG="--dev"
    fi
    
    SOURCES_OUTPUT=$("${SCRIPT_DIR}/manage_source.sh" list ${SOURCE_MODE_FLAG} --token "$ADMIN_TOKEN" 2>/dev/null || echo "ERROR")
    if [[ "$SOURCES_OUTPUT" == "ERROR" ]]; then
        echo -e "${YELLOW}  Unable to retrieve sources (MCP server may be unavailable)${NC}"
    else
        echo "$SOURCES_OUTPUT"
    fi
else
    echo -e "${YELLOW}  Unable to retrieve sources (missing admin token)${NC}"
fi

# 4. DOCUMENTS COUNT
print_section "Document Statistics" "scripts/manage_document.sh stats, ChromaDB API"

if [[ -n "$ADMIN_TOKEN" ]]; then
    # Use the stats command which is designed for this purpose
    DOC_STATS_OUTPUT=$("${SCRIPT_DIR}/manage_document.sh" stats ${SOURCE_MODE_FLAG} --token "$ADMIN_TOKEN" 2>&1)
    DOC_STATUS=$?
    
    if [[ $DOC_STATUS -eq 0 ]] && [[ -n "$DOC_STATS_OUTPUT" ]] && [[ "$DOC_STATS_OUTPUT" != *"Error"* ]]; then
        # Parse the clean output from stats command
        TOTAL_DOCS=$(echo "$DOC_STATS_OUTPUT" | awk -F': ' '/Total Documents:/ {print $2; exit}')
        EXEC_TIME=$(echo "$DOC_STATS_OUTPUT" | awk -F': ' '/Query Time:/ {print $2; exit}')
        
        if [[ -n "$TOTAL_DOCS" ]] && [[ "$TOTAL_DOCS" != "0" ]]; then
            print_key_value "Total Documents" "$TOTAL_DOCS document(s) indexed"
        else
            print_key_value "Total Documents" "No documents found"
        fi
        
        if [[ -n "$EXEC_TIME" ]]; then
            print_key_value "Query Response Time" "$EXEC_TIME"
        fi
    else
        echo -e "${YELLOW}  Unable to query documents${NC}"
    fi
    
    # File storage stats
    print_key_value "Data Directory" "${DATA_DIR}"
    print_key_value "Data Directory Size" "$(du -sh "${DATA_DIR}/storage" 2>/dev/null | cut -f1 || echo "N/A")"
    
    # ChromaDB collection count
    if command -v curl >/dev/null 2>&1; then
        CHROMA_HOST="${GOFR_IQ_CHROMADB_HOST:-localhost}"
        CHROMA_PORT="${GOFR_CHROMA_PORT:-8000}"
        if [[ "${ENV_MODE}" == "dev" ]]; then
            CHROMA_HOST="localhost"
        fi
        
        CHROMA_COLS=$(curl -sf "http://${CHROMA_HOST}:${CHROMA_PORT}/api/v1/collections" 2>/dev/null || echo "")
        if [[ -n "$CHROMA_COLS" ]]; then
            COL_COUNT=$(echo "$CHROMA_COLS" | grep -o '"name"' | wc -l)
            print_key_value "ChromaDB Collections" "$COL_COUNT collection(s)"
        fi
    fi
else
    echo -e "${YELLOW}  Unable to retrieve document stats (missing admin token)${NC}"
fi

# 5. INFRASTRUCTURE STATUS
print_section "Infrastructure Status" "docker ps, docker network ls, docker volume ls"

# Check Docker containers if in docker mode
if [[ "${ENV_MODE}" == "prod" ]] && command -v docker >/dev/null 2>&1; then
    echo "Docker Containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" --filter "name=gofr" 2>/dev/null || echo -e "${YELLOW}  Docker not available or no containers running${NC}"
    
    echo ""
    echo "Docker Networks:"
    docker network ls --filter "name=gofr" --format "table {{.Name}}\t{{.Driver}}\t{{.Scope}}" 2>/dev/null || echo -e "${YELLOW}  Unable to list networks${NC}"
    
    echo ""
    echo "Docker Volumes:"
    docker volume ls --filter "name=gofr" --format "table {{.Name}}\t{{.Driver}}" 2>/dev/null || echo -e "${YELLOW}  Unable to list volumes${NC}"
fi

# Check Python environment
print_section "Python Environment" "python3 --version, pip list"

if command -v python3 >/dev/null 2>&1; then
    print_key_value "Python Version" "$(python3 --version 2>&1)"
    print_key_value "Python Path" "$(which python3)"
    
    # Check if in venv
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        print_key_value "Virtual Environment" "${VIRTUAL_ENV}"
    else
        print_key_value "Virtual Environment" "Not activated"
    fi
    
    # Check key packages
    if python3 -c "import fastapi" 2>/dev/null; then
        FASTAPI_VERSION=$(python3 -c "import fastapi; print(fastapi.__version__)" 2>/dev/null || echo "unknown")
        print_key_value "FastAPI" "$FASTAPI_VERSION"
    fi
    
    if python3 -c "import chromadb" 2>/dev/null; then
        CHROMADB_VERSION=$(python3 -c "import chromadb; print(chromadb.__version__)" 2>/dev/null || echo "unknown")
        print_key_value "ChromaDB" "$CHROMADB_VERSION"
    fi
    
    if python3 -c "import neo4j" 2>/dev/null; then
        NEO4J_VERSION=$(python3 -c "import neo4j; print(neo4j.__version__)" 2>/dev/null || echo "unknown")
        print_key_value "Neo4j Driver" "$NEO4J_VERSION"
    fi
fi

# 6. DATA DIRECTORIES
print_section "Data Directories" "du -sh, find (filesystem)"

if [[ -d "$DATA_DIR" ]]; then
    STORAGE_SIZE=$(du -sh "${DATA_DIR}/storage" 2>/dev/null | cut -f1 || echo "N/A")
    print_key_value "Data Directory" "$DATA_DIR"
    print_key_value "Storage Size" "$STORAGE_SIZE"
    
    # Count files in storage
    if [[ -d "${DATA_DIR}/storage" ]]; then
        FILE_COUNT=$(find "${DATA_DIR}/storage" -type f 2>/dev/null | wc -l)
        print_key_value "Storage Files" "$FILE_COUNT"
    fi
else
    print_key_value "Data Directory" "Not found: $DATA_DIR"
fi

# =============================================================================
# CONFIG & ENVIRONMENT FILES
# =============================================================================
print_section "Configuration Files" "stat (filesystem)"

# Helper to show file status
show_config_file() {
    local label="$1"
    local filepath="$2"
    if [[ -f "$filepath" ]]; then
        local size=$(du -h "$filepath" 2>/dev/null | cut -f1)
        local modified=$(stat -c '%y' "$filepath" 2>/dev/null | cut -d'.' -f1 || echo "unknown")
        print_key_value "$label" "$filepath ($size, modified: $modified)"
    else
        print_key_value "$label" "${filepath} ${YELLOW}(not found)${NC}"
    fi
}

echo -e "${BOLD}Base Configuration:${NC}"
show_config_file "  Infrastructure" "${PROJECT_ROOT}/config/base/infrastructure.env"
show_config_file "  Services" "${PROJECT_ROOT}/config/base/services.env"

echo ""
echo -e "${BOLD}Generated Configuration:${NC}"
show_config_file "  Test Secrets" "${PROJECT_ROOT}/config/generated/secrets.test.env"

echo ""
echo -e "${BOLD}Docker Configuration:${NC}"
show_config_file "  Docker Compose" "${PROJECT_ROOT}/docker/docker-compose.yml"
show_config_file "  Docker .env" "${PROJECT_ROOT}/docker/.env"

echo ""
echo -e "${BOLD}Secrets & Credentials:${NC}"
show_config_file "  Bootstrap Tokens" "${PROJECT_ROOT}/secrets/bootstrap_tokens.json"
show_config_file "  Vault Root Token" "${PROJECT_ROOT}/secrets/vault_root_token"
show_config_file "  Vault Unseal Key" "${PROJECT_ROOT}/secrets/vault_unseal_key"
echo ""
echo -e "${BOLD}Library Configuration:${NC}"
show_config_file "  gofr-common .env" "${PROJECT_ROOT}/lib/gofr-common/.env"

echo ""
echo -e "${BOLD}Scripts Environment:${NC}"
show_config_file "  gofriq.env" "${PROJECT_ROOT}/scripts/gofriq.env"
show_config_file "  secrets/tokens.env" "${PROJECT_ROOT}/secrets/tokens.env"

# Summary
print_section "Summary" "health checks"

TOTAL_ISSUES=0

# Check critical services
if ! timeout 2 bash -c "echo >/dev/tcp/${MCP_HOST}/${MCP_PORT}" 2>/dev/null; then
    echo -e "${RED}✗ MCP Server not reachable${NC}"
    ((TOTAL_ISSUES++))
fi

if [[ -z "${VAULT_TOKEN:-}" ]]; then
    echo -e "${YELLOW}⚠ Vault token not configured${NC}"
    ((TOTAL_ISSUES++))
fi

if [[ -z "${GOFR_JWT_SECRET:-}" ]]; then
    echo -e "${YELLOW}⚠ JWT secret not configured${NC}"
    ((TOTAL_ISSUES++))
fi

if [[ $TOTAL_ISSUES -eq 0 ]]; then
    echo -e "${GREEN}✓ All critical checks passed${NC}"
else
    echo -e "${YELLOW}⚠ Found $TOTAL_ISSUES potential issue(s)${NC}"
fi

echo ""
echo -e "${CYAN}Environment dump complete.${NC}"
echo ""

exit 0
