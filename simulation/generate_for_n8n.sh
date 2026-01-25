#!/bin/bash
# =============================================================================
# Generate Synthetic Stories for n8n Testing (SSOT Wrapper)
# =============================================================================
# Generates synthetic news stories without validation_metadata for n8n ingestion.
#
# Usage:
#   ./simulation/generate_for_n8n.sh --count 5
#   ./simulation/generate_for_n8n.sh --count 10 --output simulation/custom_output
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Source configuration
PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
SECRETS_DIR="${PROJECT_ROOT}/secrets"
DOCKER_ENV="${PROJECT_ROOT}/docker/.env"

if [ ! -f "$PORTS_FILE" ] || [ ! -f "$SECRETS_DIR/vault_root_token" ] || [ ! -f "$DOCKER_ENV" ]; then
    echo "❌ Configuration files missing. Run bootstrap first."
    exit 1
fi

set -a
source "$PORTS_FILE"
source "$DOCKER_ENV"
set +a

# Load Vault credentials from secrets/ directory
export VAULT_TOKEN=$(cat "$SECRETS_DIR/vault_root_token")

# Load OpenRouter API key from Vault
export VAULT_ADDR="http://127.0.0.1:${GOFR_VAULT_PORT:-8201}"
OPENROUTER_KEY=$(docker exec -e VAULT_ADDR="${VAULT_ADDR}" -e VAULT_TOKEN="${VAULT_TOKEN}" \
    gofr-vault vault kv get -field=value secret/gofr/config/api-keys/openrouter 2>/dev/null || echo "")

if [ -z "$OPENROUTER_KEY" ]; then
    echo "❌ OpenRouter API key not found in Vault at secret/gofr/config/api-keys/openrouter"
    echo "   Set it with: docker exec -e VAULT_ADDR=... -e VAULT_TOKEN=... gofr-vault vault kv put secret/gofr/config/api-keys/openrouter value=YOUR_KEY"
    exit 1
fi

export GOFR_IQ_OPENROUTER_API_KEY="$OPENROUTER_KEY"

echo "🤖 Generating synthetic stories for n8n ingestion..."

# Run the python script with uv
uv run python "${SCRIPT_DIR}/generate_for_n8n.py" "$@"
