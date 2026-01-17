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
#   ./simulation/run_simulation.sh --init-groups-only
#   ./simulation/run_simulation.sh --init-tokens-only
#   ./simulation/run_simulation.sh --skip-universe --skip-clients
#   ./simulation/run_simulation.sh --skip-generate --output simulation/test_output
#
# Note: Story generation requires GOFR_IQ_OPENROUTER_API_KEY to be set.
#       Use --skip-generate to reuse existing synthetic stories.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Source production configuration (single source of truth)
PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
VAULT_INIT="${PROJECT_ROOT}/docker/.vault-init.env"

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

# Source ONLY ports and Vault credentials - secrets come from Vault directly
echo "📋 Loading configuration..."
set -a
source "$PORTS_FILE"
source "$VAULT_INIT"
set +a

# Set infrastructure endpoints (dev container is on gofr-net)
export GOFR_IQ_NEO4J_URI="${GOFR_IQ_NEO4J_URI:-bolt://gofr-neo4j:7687}"
export GOFR_IQ_NEO4J_USER="${GOFR_IQ_NEO4J_USER:-neo4j}"
export GOFR_IQ_NEO4J_PASSWORD="${NEO4J_PASSWORD:-gofr-dev-password}"
export GOFR_IQ_CHROMADB_HOST="${GOFR_IQ_CHROMADB_HOST:-gofr-chromadb}"
export GOFR_IQ_CHROMADB_PORT="${GOFR_CHROMA_INTERNAL_PORT:-8000}"
export GOFR_VAULT_URL="${GOFR_VAULT_URL:-http://gofr-vault:${GOFR_VAULT_PORT:-8201}}"

# Set Vault CLI environment for vault command
export VAULT_ADDR="${GOFR_VAULT_URL}"

# ============================================================================
# Retrieve ALL secrets from Vault (single source of truth)
# ============================================================================
echo "🔑 Retrieving secrets from Vault..."

# JWT Secret (REQUIRED - used for token signing)
JWT_SECRET=$(docker exec -e VAULT_TOKEN="$VAULT_TOKEN" gofr-vault \
    vault kv get -field=value secret/gofr/config/jwt-signing-secret 2>/dev/null || echo "")
if [ -z "$JWT_SECRET" ]; then
    echo "❌ ERROR: JWT signing secret not found in Vault"
    echo "   Run: ./docker/start-prod.sh --fresh"
    exit 1
fi
export GOFR_JWT_SECRET="$JWT_SECRET"
export GOFR_IQ_JWT_SECRET="$JWT_SECRET"

# OpenRouter API key (REQUIRED for LLM operations)
OPENROUTER_KEY=$(docker exec -e VAULT_TOKEN="$VAULT_TOKEN" gofr-vault \
    vault kv get -field=value secret/gofr/config/api-keys/openrouter 2>/dev/null || echo "")
if [ -z "$OPENROUTER_KEY" ]; then
    echo "❌ ERROR: OpenRouter API key not found in Vault"
    echo "   Store it with: ./docker/start-prod.sh --openrouter-key YOUR_KEY"
    echo "   Or manually:"
    echo "     source docker/.vault-init.env"
    echo "     docker exec -e VAULT_TOKEN=\$VAULT_TOKEN gofr-vault \\"
    echo "       vault kv put secret/gofr/config/api-keys/openrouter value=YOUR_KEY"
    exit 1
fi
export GOFR_IQ_OPENROUTER_API_KEY="$OPENROUTER_KEY"

echo "✅ All secrets loaded from Vault"
echo ""

# Run simulation
cd "$PROJECT_ROOT"
exec python3 simulation/run_simulation.py "$@"
