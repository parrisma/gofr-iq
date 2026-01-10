#!/bin/bash
# Start GOFR-IQ Docker Swarm with auth mode on
set -e

cd "$(dirname "$0")"

# Source port configuration
source ../lib/gofr-common/config/gofr_ports.sh

export GOFR_IQ_AUTH_DISABLED=false
export GOFR_IQ_OPENROUTER_API_KEY="${GOFR_IQ_OPENROUTER_API_KEY:-}"
export GOFR_VAULT_DEV_TOKEN="${GOFR_VAULT_DEV_TOKEN:-dev-root-token-a1b2c3d4e5f6}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-gofr-dev-password}"

echo "=== Starting GOFR-IQ Swarm ==="
echo "Auth: Enabled"
echo "LLM:  OpenRouter"
echo ""

docker compose up -d


