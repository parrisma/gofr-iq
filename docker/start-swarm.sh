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
#   - Secrets in lib/gofr-common/.env (GOFR_IQ_OPENROUTER_API_KEY, etc.)
#
# Usage:
#   ./start-swarm.sh
#
# Services Started:
#   - vault:    HashiCorp Vault (auth backend)
#   - neo4j:    Graph database
#   - chromadb: Vector database
#   - mcp:      MCP server (core logic)
#   - mcpo:     MCPO server (OpenAPI for OpenWebUI)
#   - web:      Web server (health checks)
#
# Configuration:
#   - Auth: ENABLED (production mode)
#   - LLM:  OpenRouter API
#   - Ports: From gofr_ports.env
# =============================================================================
set -e

cd "$(dirname "$0")"

# Load port configuration from .env file
set -a  # automatically export all variables
source ../lib/gofr-common/config/gofr_ports.env
set +a

# Production configuration: auth enabled
export GOFR_IQ_AUTH_DISABLED=false
export GOFR_IQ_OPENROUTER_API_KEY="${GOFR_IQ_OPENROUTER_API_KEY:-}"
export GOFR_VAULT_DEV_TOKEN="${GOFR_VAULT_DEV_TOKEN:-dev-root-token-a1b2c3d4e5f6}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-gofr-dev-password}"

echo "=== Starting GOFR-IQ Production Stack ==="
echo "Auth: Enabled"
echo "LLM:  OpenRouter"
echo ""

docker compose up -d

echo ""
echo "=== Container Status ==="
echo ""
docker ps --filter "name=gofr" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=== Production Stack Ready ==="
echo "MCP Server:  http://localhost:${GOFR_IQ_MCP_PORT}"
echo "MCPO Server: http://localhost:${GOFR_IQ_MCPO_PORT}"
echo "Web Server:  http://localhost:${GOFR_IQ_WEB_PORT}"
echo ""



