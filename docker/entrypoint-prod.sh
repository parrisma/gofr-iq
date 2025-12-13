#!/bin/bash
# GOFR-IQ Production Entrypoint
# Starts MCP, MCPO, and/or Web servers based on command argument
#
# Usage:
#   entrypoint-prod.sh all     # Start all servers (default)
#   entrypoint-prod.sh mcp     # Start only MCP server
#   entrypoint-prod.sh mcpo    # Start only MCPO proxy
#   entrypoint-prod.sh web     # Start only Web server

set -e

# Activate virtual environment
source /app/.venv/bin/activate

# Configuration with defaults
MCP_PORT="${GOFRIQ_MCP_PORT:-8060}"
MCPO_PORT="${GOFRIQ_MCPO_PORT:-8061}"
WEB_PORT="${GOFRIQ_WEB_PORT:-8062}"
HOST="${GOFRIQ_HOST:-0.0.0.0}"
LOG_LEVEL="${GOFRIQ_LOG_LEVEL:-INFO}"

# Create data directories
mkdir -p /app/data/storage /app/logs

# Log configuration
echo "======================================================================="
echo "GOFR-IQ Production Container"
echo "======================================================================="
echo "Environment: ${GOFRIQ_ENV:-PROD}"
echo "ChromaDB:    ${GOFRIQ_CHROMADB_HOST:-gofr-iq-chromadb}:${GOFRIQ_CHROMADB_PORT:-8000}"
echo "Neo4j:       ${GOFRIQ_NEO4J_HOST:-gofr-iq-neo4j}:${GOFRIQ_NEO4J_BOLT_PORT:-7687}"
echo "Ports:       MCP=$MCP_PORT, MCPO=$MCPO_PORT, Web=$WEB_PORT"
echo "======================================================================="

# Wait for dependencies
wait_for_service() {
    local host=$1
    local port=$2
    local name=$3
    local max_wait=${4:-60}
    local elapsed=0
    
    echo "Waiting for $name at $host:$port..."
    while ! curl -sf "http://$host:$port/api/v2/heartbeat" > /dev/null 2>&1; do
        sleep 2
        elapsed=$((elapsed + 2))
        if [ $elapsed -ge $max_wait ]; then
            echo "Warning: $name not ready after ${max_wait}s, proceeding anyway"
            return 0
        fi
        printf "."
    done
    echo ""
    echo "$name is ready"
}

# Start MCP server
start_mcp() {
    echo "Starting MCP server on port $MCP_PORT..."
    exec uvicorn app.main:mcp.streamable_http_app \
        --host "$HOST" \
        --port "$MCP_PORT" \
        --log-level "${LOG_LEVEL,,}" \
        --no-access-log
}

# Start MCPO proxy (OpenAI-compatible API)
start_mcpo() {
    local mcp_url="http://localhost:${MCP_PORT}/mcp"
    
    echo "Starting MCPO proxy on port $MCPO_PORT..."
    echo "  MCP backend: $mcp_url"
    
    exec mcpo \
        --port "$MCPO_PORT" \
        --host "$HOST" \
        --type http \
        --name "gofr-iq" \
        "$mcp_url"
}

# Start Web server (FastAPI docs/admin)
start_web() {
    echo "Starting Web server on port $WEB_PORT..."
    
    # The web server is the MCP server with the Swagger UI enabled
    # For now we just alias to MCP - can be separated later
    exec uvicorn app.main:mcp.streamable_http_app \
        --host "$HOST" \
        --port "$WEB_PORT" \
        --log-level "${LOG_LEVEL,,}"
}

# Start all servers (supervisor mode)
start_all() {
    echo "Starting all servers..."
    
    # Wait for infrastructure
    if [ -n "${GOFRIQ_CHROMADB_HOST:-}" ]; then
        wait_for_service "$GOFRIQ_CHROMADB_HOST" "${GOFRIQ_CHROMADB_PORT:-8000}" "ChromaDB" 60
    fi
    
    # Neo4j uses different health check (bolt protocol)
    # Just log that we'll connect on demand
    echo "Neo4j: ${GOFRIQ_NEO4J_HOST:-gofr-iq-neo4j}:${GOFRIQ_NEO4J_BOLT_PORT:-7687} (connect on demand)"
    
    # Start MCP server in background
    echo "Starting MCP server on port $MCP_PORT..."
    uvicorn app.main:mcp.streamable_http_app \
        --host "$HOST" \
        --port "$MCP_PORT" \
        --log-level "${LOG_LEVEL,,}" \
        --no-access-log &
    MCP_PID=$!
    
    # Wait for MCP to be ready
    sleep 3
    
    # Start MCPO proxy in background
    local mcp_url="http://localhost:${MCP_PORT}/mcp"
    echo "Starting MCPO proxy on port $MCPO_PORT -> $mcp_url..."
    mcpo \
        --port "$MCPO_PORT" \
        --host "$HOST" \
        --type http \
        --name "gofr-iq" \
        "$mcp_url" &
    MCPO_PID=$!
    
    # Start Web server (separate port for Swagger UI / health checks)
    echo "Starting Web server on port $WEB_PORT..."
    uvicorn app.main:mcp.streamable_http_app \
        --host "$HOST" \
        --port "$WEB_PORT" \
        --log-level "${LOG_LEVEL,,}" &
    WEB_PID=$!
    
    echo "======================================================================="
    echo "All servers started:"
    echo "  MCP:  http://${HOST}:${MCP_PORT}     (PID: $MCP_PID)"
    echo "  MCPO: http://${HOST}:${MCPO_PORT}     (PID: $MCPO_PID)"
    echo "  Web:  http://${HOST}:${WEB_PORT}     (PID: $WEB_PID)"
    echo "======================================================================="
    
    # Handle shutdown
    trap "echo 'Shutting down...'; kill $MCP_PID $MCPO_PID $WEB_PID 2>/dev/null; exit 0" SIGTERM SIGINT
    
    # Wait for any process to exit
    wait -n
    
    # If any process exits, kill others and exit
    echo "A server process exited, shutting down..."
    kill $MCP_PID $MCPO_PID $WEB_PID 2>/dev/null || true
    exit 1
}

# Main entrypoint
case "${1:-all}" in
    mcp)
        start_mcp
        ;;
    mcpo)
        start_mcpo
        ;;
    web)
        start_web
        ;;
    all)
        start_all
        ;;
    bash|sh)
        exec /bin/bash
        ;;
    *)
        echo "Unknown command: $1"
        echo "Usage: $0 {all|mcp|mcpo|web|bash}"
        exit 1
        ;;
esac
