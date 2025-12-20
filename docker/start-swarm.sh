#!/bin/bash
# Start GOFR-IQ Docker Swarm with no-auth mode
set -e

cd "$(dirname "$0")"

export GOFR_IQ_AUTH_DISABLED=true
# Set GOFR_IQ_OPENROUTER_API_KEY in your environment or .env file
export GOFR_IQ_OPENROUTER_API_KEY="${GOFR_IQ_OPENROUTER_API_KEY:-}"

echo "=== Starting GOFR-IQ Swarm ==="
echo "Auth: Disabled"
echo "LLM:  OpenRouter"
echo ""

docker compose up -d

echo ""
echo "=== Services ==="
echo "MCPO (OpenWebUI): http://localhost:8081"
echo "MCP Server:       http://localhost:8080"
echo "Web Health:       http://localhost:8082"
echo ""
echo "From dev container, use hostnames:"
echo "  curl http://gofr-iq-mcpo:8081/openapi.json"
echo "  curl http://gofr-iq-mcp:8080/health"
