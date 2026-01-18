#!/bin/bash
# =============================================================================
# Reset Simulation Environment (SSOT Wrapper)
# =============================================================================
# Wipes Neo4j and ChromaDB data using proper Vault-derived credentials.
#
# Usage:
#   ./simulation/reset_simulation_env.sh [--force]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Source configuration
PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
VAULT_INIT="${PROJECT_ROOT}/docker/.vault-init.env"
DOCKER_ENV="${PROJECT_ROOT}/docker/.env"

if [ ! -f "$PORTS_FILE" ] || [ ! -f "$VAULT_INIT" ] || [ ! -f "$DOCKER_ENV" ]; then
    echo "❌ Configuration files missing. Run bootstrap first."
    exit 1
fi

set -a
source "$PORTS_FILE"
source "$VAULT_INIT"
source "$DOCKER_ENV"
set +a

# Infrastructure Config
export GOFR_IQ_NEO4J_URI="${GOFR_IQ_NEO4J_URI:-bolt://gofr-neo4j:7687}"
export GOFR_IQ_NEO4J_USER="${GOFR_IQ_NEO4J_USER:-neo4j}"
export GOFR_IQ_NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"
export GOFR_IQ_CHROMADB_HOST="${GOFR_IQ_CHROMADB_HOST:-gofr-chromadb}"
export GOFR_IQ_CHROMADB_PORT="${GOFR_CHROMA_INTERNAL_PORT:-8000}"
export GOFR_VAULT_URL="${GOFR_VAULT_URL:-http://gofr-vault:${GOFR_VAULT_PORT:-8201}}"

# Check Neo4j Password
if [ -z "${GOFR_IQ_NEO4J_PASSWORD:-}" ]; then
    echo "❌ GOFR_IQ_NEO4J_PASSWORD not set in environment."
    exit 1
fi

echo "🔄 Initializing environment reset..."

# Run the python script
uv run python "${SCRIPT_DIR}/reset_simulation_env.py" "$@"
