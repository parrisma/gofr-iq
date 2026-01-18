#!/bin/bash
# =============================================================================
# Simulation Runner - Uses Production Environment
# =============================================================================
# This script sources the production environment and runs the simulation.
# It uses the same configuration as docker-compose and other manager scripts.
#
# Prerequisites:
#   - Production stack must be running (docker/start-prod.sh)
#   - Bootstrap must have been run (creates .env and .vault-init.env)
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
VAULT_INIT="${PROJECT_ROOT}/docker/.vault-init.env"
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

if [ ! -f "$VAULT_INIT" ]; then
    echo "❌ ERROR: $VAULT_INIT not found"
    echo "   Run: ./docker/start-prod.sh --fresh"
    exit 1
fi

if [ ! -f "$DOCKER_ENV" ]; then
    echo "❌ ERROR: $DOCKER_ENV not found"
    echo "   Run: ./docker/start-prod.sh or scripts/bootstrap.py"
    exit 1
fi

# Source ONLY ports, Vault credentials, and docker env - secrets come from Vault/docker/.env
echo "📋 Loading configuration..."
set -a
source "$PORTS_FILE"
source "$VAULT_INIT"
source "$DOCKER_ENV"
set +a

# Set infrastructure endpoints (dev container is on gofr-net)
export GOFR_IQ_NEO4J_URI="${GOFR_IQ_NEO4J_URI:-bolt://gofr-neo4j:7687}"
export GOFR_IQ_NEO4J_USER="${GOFR_IQ_NEO4J_USER:-neo4j}"
export GOFR_IQ_NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"
export GOFR_IQ_CHROMADB_HOST="${GOFR_IQ_CHROMADB_HOST:-gofr-chromadb}"
export GOFR_IQ_CHROMADB_PORT="${GOFR_CHROMA_INTERNAL_PORT:-8000}"
export GOFR_VAULT_URL="${GOFR_VAULT_URL:-http://gofr-vault:${GOFR_VAULT_PORT:-8201}}"

# Require Neo4j password from docker/.env (no default fallback)
if [ -z "${GOFR_IQ_NEO4J_PASSWORD:-}" ]; then
    echo "❌ ERROR: GOFR_IQ_NEO4J_PASSWORD not set (check docker/.env)"
    exit 1
fi

# Set Vault CLI environment for vault command
export VAULT_ADDR="${GOFR_VAULT_URL}"

# ============================================================================
# Retrieve secrets from Vault if not already in environment
# ============================================================================
echo "🔑 Checking secrets..."

# JWT Secret - use from docker/.env if available, otherwise get from Vault
if [ -z "${GOFR_JWT_SECRET:-}" ]; then
    echo "   Retrieving JWT from Vault..."
    JWT_SECRET=$(docker exec -e VAULT_TOKEN="$VAULT_TOKEN" gofr-vault \
        vault kv get -field=value secret/gofr/config/jwt-signing-secret 2>/dev/null || echo "")
    if [ -z "$JWT_SECRET" ]; then
        echo "❌ ERROR: JWT signing secret not in docker/.env or Vault"
        echo "   Run: ./docker/start-prod.sh --fresh"
        exit 1
    fi
    export GOFR_JWT_SECRET="$JWT_SECRET"
    export GOFR_IQ_JWT_SECRET="$JWT_SECRET"
else
    echo "   ✓ JWT from docker/.env"
    export GOFR_IQ_JWT_SECRET="${GOFR_JWT_SECRET}"
fi

# OpenRouter API key - use from docker/.env if available, otherwise get from Vault
if [ -z "${GOFR_IQ_OPENROUTER_API_KEY:-}" ]; then
    echo "   Retrieving OpenRouter key from Vault..."
    OPENROUTER_KEY=$(docker exec -e VAULT_TOKEN="$VAULT_TOKEN" gofr-vault \
        vault kv get -field=value secret/gofr/config/api-keys/openrouter 2>/dev/null || echo "")
    if [ -z "$OPENROUTER_KEY" ]; then
        echo "❌ ERROR: OpenRouter API key not in docker/.env or Vault"
        echo "   Store it with: ./docker/start-prod.sh --openrouter-key YOUR_KEY"
        exit 1
    fi
    export GOFR_IQ_OPENROUTER_API_KEY="$OPENROUTER_KEY"
else
    echo "   ✓ OpenRouter key from docker/.env"
fi

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
