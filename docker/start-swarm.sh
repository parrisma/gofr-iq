#!/bin/bash
# =============================================================================
# GOFR-IQ Production Startup Script
# =============================================================================
# This is the canonical way to start the GOFR-IQ production stack.
# Starts all services with authentication enabled via Docker Compose.
#
# Prerequisites:
#   - Docker and Docker Compose installed
#   - Port configuration in lib/gofr-common/config/gofr_ports.env
#   - Secrets in lib/gofr-common/.env (GOFR_JWT_SECRET, etc.)
#   - Vault secrets in docker/vault-secrets.env (VAULT_ROOT_TOKEN, unseal keys)
#
# Usage:
#   ./start-swarm.sh              # Full start (requires unsealed Vault)
#   ./start-swarm.sh --infra      # Start infrastructure only (for bootstrap)
#
# Services Started:
#   Infrastructure: vault, neo4j, chromadb
#   Application:    mcp, mcpo, web
#
# Configuration:
#   - Auth: ENABLED (production mode)
#   - LLM:  OpenRouter API
#   - Ports: From gofr_ports.env
# =============================================================================
set -e

cd "$(dirname "$0")"

# Parse arguments
INFRA_ONLY=false
if [[ "$1" == "--infra" ]]; then
    INFRA_ONLY=true
fi

# Load port configuration from .env file
set -a  # automatically export all variables
source ../lib/gofr-common/config/gofr_ports.env
# Load secrets (JWT_SECRET, etc.) from .env - single source of truth
source ../lib/gofr-common/.env

# Load Vault production secrets if available
if [[ -f "vault-secrets.env" ]]; then
    source vault-secrets.env
    echo "=== Loaded vault-secrets.env ==="
else
    echo "=== WARNING: vault-secrets.env not found ==="
    echo "    Using default dev token (GOFR_VAULT_DEV_TOKEN)"
    echo "    For production: cp vault-secrets.env.template vault-secrets.env"
    echo ""
fi
set +a

# Production configuration: auth enabled
export GOFR_IQ_AUTH_DISABLED=false
export GOFR_IQ_OPENROUTER_API_KEY="${GOFR_IQ_OPENROUTER_API_KEY:-}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-gofr-dev-password}"

echo "=== Starting GOFR-IQ Production Stack ==="
echo "Auth: Enabled"
echo "LLM:  OpenRouter"
echo ""

if [[ "$INFRA_ONLY" == true ]]; then
    echo "Starting infrastructure only (vault, neo4j, chromadb)..."
    docker compose up -d vault neo4j chromadb
else
    docker compose up -d
fi

echo ""
echo "=== Container Status ==="
echo ""
docker ps --filter "name=gofr" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
if [[ "$INFRA_ONLY" == true ]]; then
    echo "=== Infrastructure Started ==="
    echo ""
    echo "Next steps for fresh install:"
    echo "  1. Initialize Vault:  docker exec gofr-vault vault operator init"
    echo "  2. Save output to:    docker/vault-secrets.env"
    echo "  3. Unseal Vault:      ./unseal-vault.sh"
    echo "  4. Enable KV engine:  docker exec -e VAULT_TOKEN=\$VAULT_ROOT_TOKEN gofr-vault vault secrets enable -path=secret kv-v2"
    echo "  5. Bootstrap auth:    docker exec -e GOFR_VAULT_TOKEN=\$VAULT_ROOT_TOKEN -e GOFR_JWT_SECRET=\$GOFR_JWT_SECRET gofr-iq-web /home/gofr-iq/lib/gofr-common/scripts/bootstrap_auth.sh --docker"
    echo "  6. Start all:         ./start-swarm.sh"
else
    echo "=== Production Stack Ready ==="
    echo "MCP Server:  http://localhost:${GOFR_IQ_MCP_PORT}"
    echo "MCPO Server: http://localhost:${GOFR_IQ_MCPO_PORT}"
    echo "Web Server:  http://localhost:${GOFR_IQ_WEB_PORT}"
fi
echo ""



