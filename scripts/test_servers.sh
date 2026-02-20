#!/bin/bash
# Helper to manage the local MCP / MCPO / Web servers for integration tests.
# Keeps PID files, logs, and health checks centralized so other scripts can
# simply invoke `./scripts/test_servers.sh start|stop|status`.
#
# Usage:
#   ./scripts/test_servers.sh start    # Start all test servers
#   ./scripts/test_servers.sh stop     # Stop all test servers
#   ./scripts/test_servers.sh status   # Check status of test servers
#   ./scripts/test_servers.sh --help   # Show this help
#
# REQUIREMENTS:
#   - GOFR_IQ_MCP_PORT, GOFR_IQ_MCPO_PORT, GOFR_IQ_WEB_PORT must be set
#   - Infrastructure must be running (Vault, Neo4j, ChromaDB)
#   - Auth is Vault-sourced (JwtSecretProvider + stores); no JWT secret env var is required
#
# For test setup, load secrets first:
#   source lib/gofr-common/scripts/auth_env.sh --docker
#   ./scripts/test_servers.sh start
#
# See lib/gofr-common/scripts/readme.md for authentication guide.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_NAME="gofr-iq"
LOG_DIR="${PROJECT_ROOT}/logs"
STATE_DIR="${PROJECT_ROOT}/tmp/test-servers"
mkdir -p "${LOG_DIR}" "${STATE_DIR}"
cd "${PROJECT_ROOT}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

require_env() {
    local var="$1"
    if [ -z "${!var:-}" ]; then
        echo -e "${RED}ERROR:${NC} Environment variable ${var} is required" >&2
        exit 1
    fi
}

for required in GOFR_IQ_MCP_PORT GOFR_IQ_MCPO_PORT GOFR_IQ_WEB_PORT; do
    require_env "$required"
done

port_in_use() {
    local port=$1
    if command -v lsof >/dev/null 2>&1; then
        lsof -i ":${port}" >/dev/null 2>&1
    elif command -v ss >/dev/null 2>&1; then
        ss -tuln | grep -q ":${port} "
    else
        nc -z 127.0.0.1 "$port" >/dev/null 2>&1
    fi
}

free_port() {
    local port=$1
    if ! port_in_use "$port"; then
        return 0
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti ":${port}" | xargs -r kill -9 2>/dev/null || true
    elif command -v ss >/dev/null 2>&1; then
        ss -lptn "sport = :${port}" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d'=' -f2 | xargs -r kill -9 2>/dev/null || true
    fi
    sleep 1
}

wait_for_port() {
    local port=$1
    local pid=$2
    local log_file=$3
    for _ in {1..60}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "${RED}${PROJECT_NAME} ${log_file##*/} crashed during startup${NC}"
            tail -20 "$log_file" 2>/dev/null || true
            return 1
        fi
        if port_in_use "$port"; then
            return 0
        fi
        sleep 0.5
    done
    echo -e "${RED}Timed out waiting for port ${port}${NC}"
    tail -20 "$log_file" 2>/dev/null || true
    return 1
}

start_service() {
    local name="$1"
    local port="$2"
    local pattern="$3"
    shift 3
    local cmd=("$@")
    local pid_file="${STATE_DIR}/${name}.pid"
    local log_file="${LOG_DIR}/${PROJECT_NAME}_${name}_test.log"

    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${YELLOW}${name} already running (PID ${pid})${NC}"
            return 0
        fi
    fi

    free_port "$port"
    rm -f "$log_file" "$pid_file"
    echo -e "${YELLOW}Starting ${name} on port ${port}...${NC}"
    nohup "${cmd[@]}" >"$log_file" 2>&1 &
    local pid=$!
    echo "$pid" >"$pid_file"
    if wait_for_port "$port" "$pid" "$log_file"; then
        echo -e "${GREEN}${name} ready (PID ${pid})${NC}"
    else
        rm -f "$pid_file"
        return 1
    fi
}

stop_service() {
    local name="$1"
    local pattern="$2"
    local pid_file="${STATE_DIR}/${name}.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$pid_file"
    fi
    pkill -f "$pattern" 2>/dev/null || true
}

status_service() {
    local name="$1"
    local port="$2"
    local pid_file="${STATE_DIR}/${name}.pid"
    local status="stopped"
    local pid="-"
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            status="running"
        else
            status="dead"
        fi
    elif port_in_use "$port"; then
        status="external"
    fi
    printf "%-5s %-10s pid=%s port=%s\n" "$name" "$status" "$pid" "$port"
}

cmd_start() {
    start_service "mcp" "$GOFR_IQ_MCP_PORT" "app/main_mcp.py" \
        uv run python app/main_mcp.py \
        --port "$GOFR_IQ_MCP_PORT" \
        --host 0.0.0.0 \
        --log-level INFO

    start_service "web" "$GOFR_IQ_WEB_PORT" "app/main_web.py" \
        uv run python app/main_web.py \
        --port "$GOFR_IQ_WEB_PORT" \
        --host 0.0.0.0

    local mcp_url="http://127.0.0.1:${GOFR_IQ_MCP_PORT}/mcp"
    start_service "mcpo" "$GOFR_IQ_MCPO_PORT" "mcpo --host" \
        uv run mcpo --host 0.0.0.0 --port "$GOFR_IQ_MCPO_PORT" \
        --server-type streamable-http \
        -- "$mcp_url"
}

cmd_stop() {
    echo -e "${YELLOW}Stopping MCP/MCPO/Web servers...${NC}"
    stop_service "mcpo" "mcpo --host"
    stop_service "web" "app/main_web.py"
    stop_service "mcp" "app/main_mcp.py"
    echo -e "${GREEN}Servers stopped${NC}"
}

cmd_status() {
    echo -e "${BLUE}Test server status:${NC}"
    status_service "mcp" "$GOFR_IQ_MCP_PORT"
    status_service "mcpo" "$GOFR_IQ_MCPO_PORT"
    status_service "web" "$GOFR_IQ_WEB_PORT"
}

case "${1:-}" in
    start)
        shift
        cmd_start "$@"
        ;;
    stop)
        shift
        cmd_stop "$@"
        ;;
    status)
        shift
        cmd_status "$@"
        ;;
    *)
        echo "Usage: $(basename "$0") {start|stop|status}" >&2
        exit 1
        ;;
esac
