#!/bin/bash
# =============================================================================
# Simulation Runner - Uses Production Environment
# =============================================================================
# This script sources the production environment and runs the simulation.
# It uses the same configuration as docker-compose and other manager scripts.
#
# Prerequisites:
#   - Production stack must be running (docker/start-prod.sh)
#   - Bootstrap must have been run (creates docker/.env and secrets/)
#
# Usage:
#   ./simulation/run_simulation.sh [ARGS]
#
# Examples:
#   ./simulation/run_simulation.sh --count 10
#   ./simulation/run_simulation.sh --count 10 --regenerate  # Force new generation
#   ./simulation/run_simulation.sh --init-groups-only
#   ./simulation/run_simulation.sh --init-tokens-only
#   ./simulation/run_simulation.sh --skip-universe --skip-clients
#   ./simulation/run_simulation.sh --skip-generate --output simulation/test_output
#
# REQUIREMENTS:
#   - Production stack running: docker/start-prod.sh must have been executed
#   - secrets/: Must contain vault_root_token, vault_unseal_key (from start-prod.sh)
#   - docker/.env: Must exist (created by bootstrap.py)
#   - gofr_ports.env: Must exist (run scripts/generate_envs.sh if missing)
#   - OpenRouter API key in Vault (required for story generation, stored via start-prod.sh)
#   - Services healthy: Vault, Neo4j, ChromaDB must be running
#
# Note: Story generation requires GOFR_IQ_OPENROUTER_API_KEY to be set.
#       Use --skip-generate to reuse existing synthetic stories.
#       By default, existing stories are cached and reused (saves $ and time).
#       Use --regenerate to force new generation even if cached stories exist.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Source production configuration (single source of truth)
PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
SECRETS_DIR="${PROJECT_ROOT}/secrets"
DOCKER_ENV="${PROJECT_ROOT}/docker/.env"

echo "======================================================================="
echo "🔬 GOFR-IQ Simulation Runner"
echo "======================================================================="

# Check prerequisites
if [ ! -f "$PORTS_FILE" ]; then
    echo "❌ ERROR: $PORTS_FILE not found"
    echo "   Run: ./scripts/generate_envs.sh"
    exit 1
fi

if [ ! -f "$SECRETS_DIR/vault_root_token" ]; then
    echo "❌ ERROR: $SECRETS_DIR/vault_root_token not found"
    echo "   Run: ./docker/start-prod.sh --fresh"
    exit 1
fi

if [ ! -f "$DOCKER_ENV" ]; then
    echo "❌ ERROR: $DOCKER_ENV not found"
    echo "   Run: ./docker/start-prod.sh or scripts/bootstrap.py"
    exit 1
fi

# Source ports and docker env - Vault credentials loaded from secrets dir
echo "📋 Loading configuration..."
set -a
source "$PORTS_FILE"
source "$DOCKER_ENV"
set +a

# Load Vault credentials from secrets directory (Zero-Trust Bootstrap)
export VAULT_TOKEN=$(cat "$SECRETS_DIR/vault_root_token")
if [ -f "$SECRETS_DIR/vault_unseal_key" ]; then
    export VAULT_UNSEAL_KEY=$(cat "$SECRETS_DIR/vault_unseal_key")
fi

# Set infrastructure endpoints (dev container is on gofr-net)
# ZERO-TRUST BOOTSTRAP: Use explicit values from docker/.env (no defaults)
if [ -z "${GOFR_IQ_NEO4J_URI:-}" ]; then export GOFR_IQ_NEO4J_URI="bolt://gofr-neo4j:7687"; fi
if [ -z "${GOFR_IQ_NEO4J_USER:-}" ]; then export GOFR_IQ_NEO4J_USER="neo4j"; fi
if [ -z "${GOFR_IQ_CHROMADB_HOST:-}" ]; then export GOFR_IQ_CHROMADB_HOST="gofr-chromadb"; fi
if [ -z "${GOFR_IQ_CHROMADB_PORT:-}" ]; then export GOFR_IQ_CHROMADB_PORT="8000"; fi
if [ -z "${GOFR_VAULT_URL:-}" ]; then export GOFR_VAULT_URL="http://gofr-vault:${GOFR_VAULT_PORT}"; fi

# ZERO-TRUST BOOTSTRAP: Neo4j password retrieved from Vault below
# (Services get it via AppRole, simulation script retrieves it explicitly)

# Set Vault CLI environment for vault command
export VAULT_ADDR="${GOFR_VAULT_URL}"

# ============================================================================
# Retrieve secrets from Vault ONLY (Zero-Trust Bootstrap)
# ============================================================================
echo "🔑 Retrieving secrets from Vault..."

# JWT Secret - MUST come from Vault (no docker/.env fallback)
echo "   Retrieving JWT from Vault..."
JWT_SECRET=$(docker exec -e VAULT_TOKEN="$VAULT_TOKEN" gofr-vault \
    vault kv get -field=value secret/gofr/config/jwt-signing-secret 2>/dev/null || echo "")
if [ -z "$JWT_SECRET" ]; then
    echo "❌ ERROR: JWT signing secret not found in Vault"
    echo "   Run: ./docker/start-prod.sh --fresh"
    exit 1
fi
export GOFR_JWT_SECRET="$JWT_SECRET"
export GOFR_IQ_JWT_SECRET="$JWT_SECRET"
echo "   ✓ JWT from Vault"

# Neo4j password - MUST come from Vault
echo "   Retrieving Neo4j password from Vault..."
NEO4J_PASSWORD=$(docker exec -e VAULT_TOKEN="$VAULT_TOKEN" gofr-vault \
    vault kv get -field=value secret/gofr/config/neo4j-password 2>/dev/null || echo "")
if [ -z "$NEO4J_PASSWORD" ]; then
    echo "❌ ERROR: Neo4j password not found in Vault"
    echo "   Run: ./docker/start-prod.sh --fresh"
    exit 1
fi
export GOFR_IQ_NEO4J_PASSWORD="$NEO4J_PASSWORD"
echo "   ✓ Neo4j password from Vault"

# OpenRouter API key - MUST come from Vault (no docker/.env fallback)
echo "   Retrieving OpenRouter key from Vault..."
OPENROUTER_KEY=$(docker exec -e VAULT_TOKEN="$VAULT_TOKEN" gofr-vault \
    vault kv get -field=value secret/gofr/config/api-keys/openrouter 2>/dev/null || echo "")
if [ -z "$OPENROUTER_KEY" ]; then
    echo "❌ ERROR: OpenRouter API key not found in Vault"
    echo "   Store it with: ./docker/start-prod.sh --openrouter-key YOUR_KEY"
    exit 1
fi
export GOFR_IQ_OPENROUTER_API_KEY="$OPENROUTER_KEY"
echo "   ✓ OpenRouter key from Vault"

# ============================================================================
# Health Checks & Positive Affirmations (Pre-Flight)
# ============================================================================
echo "🏥 performing pre-flight system checks..."

check_service() {
    local name=$1
    local host=$2
    local port=$3
    local endpoint=$4
    local expected=$5
    
    printf "   Checking %-15s " "$name..."
    if curl -s -o /dev/null -w "%{http_code}" "http://${host}:${port}${endpoint}" | grep -q "$expected" >/dev/null 2>&1; then
        echo "✅ UP"
    else
        # Try simple TCP check if http fails (e.g. for Neo4j Bolt port)
        if timeout 1 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" 2>/dev/null; then
            echo "✅ UP (TCP)"
        else
            echo "❌ DOWN"
            echo "   ERROR: Could not connect to $name at ${host}:${port}"
            return 1
        fi
    fi
}

# Vault (already passed env check, but verify connectivity)
# Strip protocol for TCP check or use curl
VAULT_HOST=$(echo $GOFR_VAULT_URL | awk -F/ '{print $3}' | cut -d: -f1)
check_service "Vault" "$VAULT_HOST" "${GOFR_VAULT_PORT:-8201}" "/v1/sys/health" "200\|429\|472\|473" || exit 1

# Neo4j (HTTP console port 7474 usually, but we check Bolt 7687 via TCP)
# GOFR_IQ_NEO4J_URI is typically bolt://hostname:7687
NEO4J_HOST=$(echo $GOFR_IQ_NEO4J_URI | awk -F/ '{print $3}' | cut -d: -f1)
NEO4J_PORT=$(echo $GOFR_IQ_NEO4J_URI | awk -F/ '{print $3}' | cut -d: -f2)
[ -z "$NEO4J_PORT" ] && NEO4J_PORT=7687
# Simple TCP check for Neo4j Bolt
printf "   Checking %-15s " "Neo4j Bolt..."
if timeout 1 bash -c "cat < /dev/null > /dev/tcp/${NEO4J_HOST}/${NEO4J_PORT}" 2>/dev/null; then
    echo "✅ UP"
else
    echo "❌ DOWN"
    echo "   ERROR: Could not connect to Neo4j at ${NEO4J_HOST}:${NEO4J_PORT}"
    exit 1
fi

# ChromaDB
check_service "ChromaDB" "$GOFR_IQ_CHROMADB_HOST" "$GOFR_IQ_CHROMADB_PORT" "/api/v1/heartbeat" "200" || exit 1

echo "✨ System infrastructure is ready."

echo "✅ All secrets loaded from Vault"
echo ""

# Run simulation
cd "$PROJECT_ROOT"
exec uv run python simulation/run_simulation.py "$@"
