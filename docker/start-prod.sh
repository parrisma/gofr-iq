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
VAULT_INIT_FILE="${SCRIPT_DIR}/.vault-init.env"
DOCKER_ENV_FILE="${SCRIPT_DIR}/.env"

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
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

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
    
    log_info "Stopping all containers..."
    cd "$SCRIPT_DIR"
    docker compose down 2>/dev/null || true
    
    log_info "Removing docker volumes..."
    docker volume rm gofr-vault-data gofr-vault-logs gofr-iq-neo4j-data gofr-iq-neo4j-logs gofr-iq-chroma-data 2>/dev/null || true
    
    log_info "Clearing data directories..."
    rm -rf "${PROJECT_ROOT}/data/storage/"* 2>/dev/null || true
    rm -rf "${PROJECT_ROOT}/data/auth/"* 2>/dev/null || true
    rm -rf "${PROJECT_ROOT}/data/sessions/"* 2>/dev/null || true
    
    log_info "Removing credential files..."
    rm -f "$VAULT_INIT_FILE" "$DOCKER_ENV_FILE" 2>/dev/null || true
    rm -rf "${PROJECT_ROOT}/config/generated" 2>/dev/null || true
    
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

# Step 3: Source Vault credentials if they exist
if [ -f "$VAULT_INIT_FILE" ]; then
    log_info "Loading existing Vault credentials..."
    source "$VAULT_INIT_FILE"
    log_success "Vault credentials loaded"
fi

# Step 4: Stop existing services (preserve volumes)
log_info "Stopping existing services..."
cd "$SCRIPT_DIR"
docker compose down 2>/dev/null || true
log_success "Existing services stopped"

# Step 5: Start Vault first
log_info "Starting Vault container..."

docker compose up -d vault

# Wait for Vault to be reachable
log_info "Waiting for Vault to be ready..."

# Determine Vault address based on environment
if [ -f /.dockerenv ]; then
    # We're in a dev container - use network name
    VAULT_ADDR="http://gofr-vault:${GOFR_VAULT_PORT:-8201}"
else
    # Host machine - use localhost
    VAULT_ADDR="http://localhost:${GOFR_VAULT_PORT:-8201}"
fi

for i in {1..30}; do
    if curl -s "${VAULT_ADDR}/v1/sys/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Check Vault status
VAULT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${VAULT_ADDR}/v1/sys/health" 2>/dev/null || echo "000")
log_info "Vault status code: $VAULT_STATUS"

case "$VAULT_STATUS" in
    "200")
        log_success "Vault is initialized and unsealed"
        ;;
    "429")
        # Standby node - treat as healthy
        log_success "Vault is initialized and unsealed (standby)"
        ;;
    "501")
        # Not initialized - bootstrap will handle this
        if [ "$FRESH_INSTALL" = true ]; then
            log_info "Fresh Vault detected - bootstrap will auto-initialize"
        else
            log_warn "Vault not initialized. Run with --fresh for auto-init"
            log_warn "Or manually: docker exec gofr-vault vault operator init"
            exit 1
        fi
        ;;
    "503")
        # Sealed - need to unseal before bootstrap
        if [ -n "${VAULT_UNSEAL_KEY:-}" ]; then
            log_info "Unsealing Vault..."
            curl -s -X PUT "${VAULT_ADDR}/v1/sys/unseal" \
                -H "Content-Type: application/json" \
                -d "{\"key\": \"${VAULT_UNSEAL_KEY}\"}" >/dev/null
            log_success "Vault unsealed"
        else
            # No unseal key - this is OK if FRESH_INSTALL, bootstrap will init fresh
            if [ "$FRESH_INSTALL" = true ]; then
                log_warn "Vault is sealed but no VAULT_UNSEAL_KEY - bootstrap will reinitialize"
            else
                log_error "Vault is sealed and no VAULT_UNSEAL_KEY found"
                log_info "Source the credentials: source docker/.vault-init.env"
                exit 1
            fi
        fi
        ;;
    *)
        log_error "Vault not reachable (HTTP $VAULT_STATUS)"
        exit 1
        ;;
esac

# Step 5.5: Validate JWT secret consistency (docker/.env vs Vault)
if [ -n "${GOFR_JWT_SECRET:-}" ] && [ -n "${VAULT_TOKEN:-}" ]; then
    VAULT_JWT=$(docker exec -e VAULT_TOKEN="${VAULT_TOKEN}" gofr-vault \
        vault kv get -field=value secret/gofr/config/jwt-signing-secret 2>/dev/null || true)
    if [ -n "$VAULT_JWT" ] && [ "$VAULT_JWT" != "$GOFR_JWT_SECRET" ]; then
        log_error "GOFR_JWT_SECRET in docker/.env differs from Vault; refusing to start."
        log_info "Regenerate docker/.env via scripts/bootstrap.py or remove stale docker/.env before retry."
        exit 1
    fi
fi

# Step 6: Run bootstrap
log_info "Running bootstrap.py..."
cd "$PROJECT_ROOT"

BOOTSTRAP_ARGS=""
if [ "$FRESH_INSTALL" = true ]; then
    BOOTSTRAP_ARGS="--auto-init"
fi
if [ -n "$OPENROUTER_KEY" ]; then
    BOOTSTRAP_ARGS="$BOOTSTRAP_ARGS --openrouter-key $OPENROUTER_KEY"
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

# Step 7: Start all services
log_info "Starting all services..."
cd "$SCRIPT_DIR"

# Don't recreate Vault - it's already running and healthy
docker compose up -d neo4j chromadb
# Wait for infra
sleep 5
docker compose up -d mcp mcpo web

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
echo "Credentials saved to: docker/.vault-init.env"
echo "Environment saved to: docker/.env"
echo ""
