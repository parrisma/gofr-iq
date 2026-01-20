#!/bin/bash
# =============================================================================
# GOFR-IQ Production Start Script
# =============================================================================
# Single-command production startup with automatic Vault initialization.
#
# Usage:
#   ./docker/start-prod.sh              # Normal start (reuses existing Vault)
#   ./docker/start-prod.sh --fresh      # Fresh install (init new Vault)
#   ./docker/start-prod.sh --reset      # Nuke & pave (wipe all data first)
#
# This script:
# 1. Sources port configuration
# 2. Starts Vault container
# 3. Auto-initializes/unseals Vault (if needed)
# 4. Runs bootstrap.py to setup auth
# 5. Starts all services
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
SECRETS_DIR="${PROJECT_ROOT}/secrets"
DOCKER_ENV_FILE="${SCRIPT_DIR}/.env"

# Detect host path for volume mounts (handles dev container scenario)
# ZERO-TRUST BOOTSTRAP: Fail hard if detection fails (no fallback)
if [ -f /.dockerenv ]; then
    # Inside dev container - need to find the HOST path
    HOST_PROJECT_ROOT=$(docker inspect gofr-iq-dev --format='{{range .Mounts}}{{if eq .Destination "/home/gofr/devroot/gofr-iq"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)
    if [ -z "$HOST_PROJECT_ROOT" ]; then
        log_error "Failed to detect host project root from dev container"
        log_info "Ensure gofr-iq-dev container is running"
        exit 1
    fi
else
    # On host directly
    HOST_PROJECT_ROOT="$PROJECT_ROOT"
fi
export HOST_PROJECT_ROOT

# Parse arguments
FRESH_INSTALL=false
RESET_ALL=false
OPENROUTER_KEY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fresh)
            FRESH_INSTALL=true
            shift
            ;;
        --reset)
            RESET_ALL=true
            FRESH_INSTALL=true
            shift
            ;;
        --openrouter-key)
            OPENROUTER_KEY="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--fresh] [--reset] [--openrouter-key KEY]"
            echo ""
            echo "Options:"
            echo "  --fresh          Initialize new Vault (use after first install)"
            echo "  --reset          Wipe all data and reinitialize (nuke & pave)"
            echo "  --openrouter-key Store OpenRouter API key in Vault"
            echo ""
            echo "REQUIREMENTS:"
            echo "  - Docker must be installed and running"
            echo "  - gofr_ports.env must exist (run scripts/generate_envs.sh first)"
            echo "  - OpenRouter API key (prompted or via --openrouter-key flag)"
            echo "  - Must run from project root or inside gofr-iq-dev container"
            echo ""
            echo "OUTPUTS:"
            echo "  - secrets/vault_root_token: Vault root token (for emergency recovery)"
            echo "  - secrets/vault_unseal_key: Vault unseal key (auto-unseals on restart)"
            echo "  - secrets/bootstrap_tokens.json: 2x 365-day admin tokens (for operators)"
            echo "  - secrets/service_creds/: AppRole credentials (auto-mounted to services)"
            echo ""
            echo "AUTHENTICATION:"
            echo "  After startup, operators can manage auth via:"
            echo "    source lib/gofr-common/scripts/auth_env.sh --docker"
            echo "    lib/gofr-common/scripts/auth_manager.sh list-groups"
            echo ""
            echo "  See lib/gofr-common/scripts/readme.md for full guide."
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Require OpenRouter API key (prompt if interactive, fail fast otherwise)
if [ -z "$OPENROUTER_KEY" ]; then
    if [ -t 0 ]; then
        echo ""
        echo "🔑 OpenRouter API Key Required"
        echo "The key powers LLM features (entity extraction, embeddings)."
        read -s -p "Enter OpenRouter API Key (input hidden): " OPENROUTER_KEY
        echo ""
        if [ -z "$OPENROUTER_KEY" ]; then
            log_error "OpenRouter API key is required. Re-run with --openrouter-key YOUR_KEY."
            exit 1
        fi
    else
        log_error "OpenRouter API key not provided. Pass --openrouter-key YOUR_KEY or set GOFR_IQ_OPENROUTER_API_KEY."
        exit 1
    fi
fi

echo ""
echo "======================================================================="
echo "🚀 GOFR-IQ Production Startup"
echo "======================================================================="

# Step 0: Reset if requested
if [ "$RESET_ALL" = true ]; then
    log_warn "RESET MODE: This will destroy all data!"
    read -p "Are you sure? Type 'yes' to continue: " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "Aborted."
        exit 0
    fi
    
    log_info "Stopping gofr-iq production containers..."
    # Stop only gofr-iq production containers (not dev container we're running in)
    docker stop gofr-vault gofr-neo4j gofr-chromadb gofr-mcp gofr-mcpo gofr-web 2>/dev/null || true
    docker rm gofr-vault gofr-neo4j gofr-chromadb gofr-mcp gofr-mcpo gofr-web 2>/dev/null || true
    
    log_info "Removing docker volumes..."
    docker volume rm gofr-vault-data gofr-vault-logs gofr-iq-neo4j-data gofr-iq-neo4j-logs gofr-iq-chroma-data 2>/dev/null || true
    
    log_info "Clearing data directories..."
    rm -rf "${PROJECT_ROOT}/data/storage/"* 2>/dev/null || true
    rm -rf "${PROJECT_ROOT}/data/auth/"* 2>/dev/null || true
    rm -rf "${PROJECT_ROOT}/data/sessions/"* 2>/dev/null || true
    
    log_info "Removing credential files..."
    rm -f "$DOCKER_ENV_FILE" 2>/dev/null || true
    rm -rf "${PROJECT_ROOT}/config/generated" 2>/dev/null || true
    rm -rf "$SECRETS_DIR" 2>/dev/null || true
    
    log_success "Reset complete - environment is clean"
fi

# Step 1: Source port configuration
log_info "Loading port configuration..."
if [ ! -f "$PORTS_FILE" ]; then
    log_error "Port config not found: $PORTS_FILE"
    log_info "Run: ./scripts/generate_envs.sh first"
    exit 1
fi
set -a
source "$PORTS_FILE"
set +a
log_success "Ports loaded"

# Step 2: Source existing docker env if present
if [ -f "$DOCKER_ENV_FILE" ]; then
    set -a
    source "$DOCKER_ENV_FILE"
    set +a
fi

# Step 4: Stop existing services (preserve volumes)
log_info "Stopping existing services..."
cd "$SCRIPT_DIR"
docker compose down 2>/dev/null || true
log_success "Existing services stopped"

# Step 5: Start Vault first
log_info "Starting Vault container..."

docker compose up -d vault
# Determine Vault address based on environment and let bootstrap handle readiness
if [ -f /.dockerenv ]; then
    VAULT_ADDR="http://gofr-vault:${GOFR_VAULT_PORT:-8201}"
else
    VAULT_ADDR="http://localhost:${GOFR_VAULT_PORT:-8201}"
fi
export VAULT_ADDR
log_info "Delegating Vault readiness to bootstrap.py (auto-init/unseal if needed)..."

# Step 6: Run bootstrap
log_info "Running bootstrap.py..."
cd "$PROJECT_ROOT"

BOOTSTRAP_ARGS=""
if [ "$FRESH_INSTALL" = true ]; then
    BOOTSTRAP_ARGS="--auto-init"
fi
if [ -n "$OPENROUTER_KEY" ]; then
    BOOTSTRAP_ARGS="$BOOTSTRAP_ARGS --openrouter-key $OPENROUTER_KEY"
    export GOFR_IQ_OPENROUTER_API_KEY="$OPENROUTER_KEY"
fi

# Set VAULT_ADDR for bootstrap (use container name when inside docker network)
export VAULT_ADDR="http://gofr-vault:${GOFR_VAULT_PORT:-8201}"

# Check if we're in a container (dev container)
if [ -f /.dockerenv ]; then
    # We're in a container - use network name
    export VAULT_ADDR="http://gofr-vault:${GOFR_VAULT_PORT:-8201}"
else
    # Host machine - use localhost
    export VAULT_ADDR="http://localhost:${GOFR_VAULT_PORT:-8201}"
fi

uv run scripts/bootstrap.py $BOOTSTRAP_ARGS

# Step 6.1: Run AppRole setup (Zero-Trust Bootstrap)
log_info "Setting up AppRole identities..."
uv run scripts/setup_approle.py
log_success "AppRole identities created"

# Reload generated env
if [ -f "$DOCKER_ENV_FILE" ]; then
    set -a
    source "$DOCKER_ENV_FILE"
    set +a
fi

# Step 6.5: Merge port configuration into docker .env for docker compose
log_info "Merging port configuration into docker .env..."
if [ -f "$PORTS_FILE" ]; then
    # Check if ports are already in .env (avoid duplicates)
    if ! grep -q "GOFR_IQ_MCP_PORT" "$DOCKER_ENV_FILE" 2>/dev/null; then
        echo "" >> "$DOCKER_ENV_FILE"
        echo "# Port Configuration (merged from gofr-common)" >> "$DOCKER_ENV_FILE"
        cat "$PORTS_FILE" >> "$DOCKER_ENV_FILE"
        log_success "Port configuration merged"
    else
        log_info "Port configuration already present in .env"
    fi
fi

# Also merge shared secrets if they exist
SHARED_ENV="${PROJECT_ROOT}/lib/gofr-common/.env"
if [ -f "$SHARED_ENV" ]; then
    # Merge any missing secrets from gofr-common/.env
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        # Only add if not already present
        if ! grep -q "^${key}=" "$DOCKER_ENV_FILE" 2>/dev/null; then
            echo "${key}=${value}" >> "$DOCKER_ENV_FILE"
        fi
    done < "$SHARED_ENV"
fi

# Step 6.9: Load secrets from Vault (Zero-Trust: NO Docker secrets, NO fallbacks)
log_info "Loading secrets from Vault..."

# Get Vault root token from bootstrap output
VAULT_TOKEN=$(cat "${PROJECT_ROOT}/secrets/vault_root_token")
export VAULT_TOKEN

# Load Neo4j password (REQUIRED - fail if missing)
NEO4J_PASSWORD=$(docker exec -e VAULT_ADDR="${VAULT_ADDR}" -e VAULT_TOKEN="${VAULT_TOKEN}" \
    gofr-vault vault kv get -field=value secret/gofr/config/neo4j-password 2>/dev/null)
if [ -z "$NEO4J_PASSWORD" ]; then
    log_error "Failed to load Neo4j password from Vault"
    exit 1
fi
export NEO4J_PASSWORD
log_success "Loaded Neo4j password from Vault"

# Load OpenRouter API key (REQUIRED - fail if missing)
if [ -z "$GOFR_IQ_OPENROUTER_API_KEY" ]; then
    GOFR_IQ_OPENROUTER_API_KEY=$(docker exec -e VAULT_ADDR="${VAULT_ADDR}" -e VAULT_TOKEN="${VAULT_TOKEN}" \
        gofr-vault vault kv get -field=value secret/gofr/config/api-keys/openrouter 2>/dev/null)
    if [ -z "$GOFR_IQ_OPENROUTER_API_KEY" ]; then
        log_error "Failed to load OpenRouter API key from Vault"
        exit 1
    fi
    export GOFR_IQ_OPENROUTER_API_KEY
    log_success "Loaded OpenRouter API key from Vault"
fi

# Step 7: Start all services
log_info "Starting all services..."
cd "$SCRIPT_DIR"

# Start infra services (don't recreate Vault - it's already running)
docker compose up -d neo4j chromadb

# Wait for infra to be healthy
log_info "Waiting for infrastructure services..."
sleep 5

# Force recreate app services to pick up new volume mounts (AppRole credentials)
docker compose up -d --force-recreate mcp mcpo web

# Step 8: Wait for health checks
log_info "Waiting for services to be healthy..."
sleep 5

# Check status
docker compose ps

echo ""
log_success "======================================================================="
log_success "🎉 GOFR-IQ Production Stack Started!"
log_success "======================================================================="
echo ""
echo "Services:"
echo "  - Vault:    http://localhost:${GOFR_VAULT_PORT:-8201}"
echo "  - MCP:      http://localhost:${GOFR_IQ_MCP_PORT:-8080}"
echo "  - Web:      http://localhost:${GOFR_IQ_WEB_PORT:-8082}"
echo "  - Neo4j:    http://localhost:${GOFR_NEO4J_HTTP_PORT:-7474}"
echo "  - ChromaDB: http://localhost:${GOFR_CHROMA_PORT:-8000}"
echo ""
echo "Credentials saved to: secrets/"
echo "Environment saved to: docker/.env"
echo ""

# Post-start snapshot
log_info "Dumping environment snapshot (docker mode)..."
cd "$PROJECT_ROOT"
./scripts/dump_environment.sh --docker
cd "$SCRIPT_DIR"
