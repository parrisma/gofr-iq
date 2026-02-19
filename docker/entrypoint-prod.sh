#!/bin/bash
# gofr-iq Production Entrypoint
# Starts MCP, MCPO, and Web servers via supervisor
set -euo pipefail

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
log_info() { echo "[$(timestamp)] [INFO] $*"; }
log_warn() { echo "[$(timestamp)] [WARN] $*"; }
log_error() { echo "[$(timestamp)] [ERROR] $*" >&2; }

trap 'log_error "Entrypoint failed at line $LINENO"' ERR

# Load centralized port configuration from .env file
GOFR_PORTS_FILE="/home/gofr-iq/lib/gofr-common/config/gofr_ports.env"
if [ -f "${GOFR_PORTS_FILE}" ]; then
    set -a  # automatically export all variables
    # shellcheck disable=SC1090
    source "${GOFR_PORTS_FILE}"
    set +a
else
    log_warn "Port configuration file not found: ${GOFR_PORTS_FILE}"
    log_warn "Continuing with environment defaults"
fi

# Environment variables
# JWT signing secret is sourced from Vault at runtime; no JWT secret env var is required.
AUTH_DISABLED="${GOFR_IQ_AUTH_DISABLED:-false}"
export GOFR_IQ_AUTH_DISABLED="$AUTH_DISABLED"

# Port configuration (from gofr_ports.sh)
MCP_PORT="${GOFR_IQ_MCP_PORT:-8080}"
MCPO_PORT="${GOFR_IQ_MCPO_PORT:-8081}"
WEB_PORT="${GOFR_IQ_WEB_PORT:-8082}"

export MCP_PORT
export MCPO_PORT
export WEB_PORT
export GOFR_IQ_MCP_PORT="$MCP_PORT"
export GOFR_IQ_MCPO_PORT="$MCPO_PORT"
export GOFR_IQ_WEB_PORT="$WEB_PORT"
# Legacy env var kept for supervisor config compatibility (unused by upgraded auth).
export JWT_SECRET="${JWT_SECRET:-}"

# gofr-iq specific environment
export GOFR_IQ_DATA_DIR="${GOFR_IQ_DATA_DIR:-/home/gofr-iq/data}"
export GOFR_IQ_STORAGE_DIR="${GOFR_IQ_STORAGE_DIR:-/home/gofr-iq/data/storage}"
export GOFR_IQ_AUTH_DIR="${GOFR_IQ_AUTH_DIR:-/home/gofr-iq/data/auth}"

# Neo4j connection (optional)
export NEO4J_URI="${NEO4J_URI:-bolt://gofr-neo4j:7687}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"

# ChromaDB connection (from gofr_ports.sh)
export CHROMA_HOST="${CHROMA_HOST:-gofr-chromadb}"
export CHROMA_PORT="${GOFR_CHROMA_INTERNAL_PORT:-${GOFR_CHROMA_PORT:-8000}}"

# Path to venv
VENV_PATH="/home/gofr-iq/.venv"

log_info "=== gofr-iq Production Container ==="
log_info "MCP Port:  ${MCP_PORT}"
log_info "MCPO Port: ${MCPO_PORT}"
log_info "Web Port:  ${WEB_PORT}"
log_info "Data Dir:  ${GOFR_IQ_DATA_DIR}"
log_info "Chroma:    ${CHROMA_HOST}:${CHROMA_PORT}"

# Ensure data directories exist with correct permissions
mkdir -p "${GOFR_IQ_DATA_DIR}" "${GOFR_IQ_STORAGE_DIR}" "${GOFR_IQ_AUTH_DIR}"
chown -R gofr-iq:gofr-iq /home/gofr-iq/data

# Generate supervisor configuration
cat > /etc/supervisor/conf.d/gofr-iq.conf << EOF
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid
user=root

[program:mcp]
command=${VENV_PATH}/bin/python -m app.main_mcp
directory=/home/gofr-iq
user=gofr-iq
autostart=true
autorestart=true
stdout_logfile=/home/gofr-iq/logs/mcp.log
stderr_logfile=/home/gofr-iq/logs/mcp-error.log
environment=PATH="${VENV_PATH}/bin:%(ENV_PATH)s",VIRTUAL_ENV="${VENV_PATH}",JWT_SECRET="%(ENV_JWT_SECRET)s",GOFR_IQ_AUTH_DISABLED="%(ENV_GOFR_IQ_AUTH_DISABLED)s",MCP_PORT="%(ENV_MCP_PORT)s",GOFR_IQ_DATA_DIR="%(ENV_GOFR_IQ_DATA_DIR)s",GOFR_IQ_STORAGE_DIR="%(ENV_GOFR_IQ_STORAGE_DIR)s",GOFR_IQ_AUTH_DIR="%(ENV_GOFR_IQ_AUTH_DIR)s",NEO4J_URI="%(ENV_NEO4J_URI)s",NEO4J_USER="%(ENV_NEO4J_USER)s",NEO4J_PASSWORD="%(ENV_NEO4J_PASSWORD)s",CHROMA_HOST="%(ENV_CHROMA_HOST)s",CHROMA_PORT="%(ENV_CHROMA_PORT)s"

[program:mcpo]
command=${VENV_PATH}/bin/mcpo --host 0.0.0.0 --port ${MCPO_PORT} --server-type streamable-http -- http://127.0.0.1:${MCP_PORT}/mcp
directory=/home/gofr-iq
user=gofr-iq
autostart=true
autorestart=true
stdout_logfile=/home/gofr-iq/logs/mcpo.log
stderr_logfile=/home/gofr-iq/logs/mcpo-error.log
environment=PATH="${VENV_PATH}/bin:%(ENV_PATH)s",VIRTUAL_ENV="${VENV_PATH}",JWT_SECRET="%(ENV_JWT_SECRET)s",GOFR_IQ_AUTH_DISABLED="%(ENV_GOFR_IQ_AUTH_DISABLED)s",GOFR_IQ_DATA_DIR="%(ENV_GOFR_IQ_DATA_DIR)s",GOFR_IQ_STORAGE_DIR="%(ENV_GOFR_IQ_STORAGE_DIR)s",GOFR_IQ_AUTH_DIR="%(ENV_GOFR_IQ_AUTH_DIR)s",NEO4J_URI="%(ENV_NEO4J_URI)s",NEO4J_USER="%(ENV_NEO4J_USER)s",NEO4J_PASSWORD="%(ENV_NEO4J_PASSWORD)s",CHROMA_HOST="%(ENV_CHROMA_HOST)s",CHROMA_PORT="%(ENV_CHROMA_PORT)s"

[program:web]
command=${VENV_PATH}/bin/python -m app.main_web
directory=/home/gofr-iq
user=gofr-iq
autostart=true
autorestart=true
stdout_logfile=/home/gofr-iq/logs/web.log
stderr_logfile=/home/gofr-iq/logs/web-error.log
environment=PATH="${VENV_PATH}/bin:%(ENV_PATH)s",VIRTUAL_ENV="${VENV_PATH}",JWT_SECRET="%(ENV_JWT_SECRET)s",GOFR_IQ_AUTH_DISABLED="%(ENV_GOFR_IQ_AUTH_DISABLED)s",WEB_PORT="%(ENV_WEB_PORT)s",GOFR_IQ_DATA_DIR="%(ENV_GOFR_IQ_DATA_DIR)s",GOFR_IQ_STORAGE_DIR="%(ENV_GOFR_IQ_STORAGE_DIR)s",GOFR_IQ_AUTH_DIR="%(ENV_GOFR_IQ_AUTH_DIR)s",NEO4J_URI="%(ENV_NEO4J_URI)s",NEO4J_USER="%(ENV_NEO4J_USER)s",NEO4J_PASSWORD="%(ENV_NEO4J_PASSWORD)s",CHROMA_HOST="%(ENV_CHROMA_HOST)s",CHROMA_PORT="%(ENV_CHROMA_PORT)s"
EOF

log_info "Starting supervisor..."
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
