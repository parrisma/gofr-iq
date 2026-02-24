#!/bin/bash
set -euo pipefail

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
log_info() { echo "[$(timestamp)] [INFO] $*"; }
log_warn() { echo "[$(timestamp)] [WARN] $*"; }
log_error() { echo "[$(timestamp)] [ERROR] $*" >&2; }

trap 'log_error "Entrypoint failed at line $LINENO"' ERR

# Standard GOFR user paths - all projects use 'gofr' user
GOFR_USER="gofr"
PROJECT_DIR="/home/${GOFR_USER}/devroot/gofr-iq"
# gofr-common is now a git submodule in lib/gofr-common
COMMON_DIR="$PROJECT_DIR/lib/gofr-common"
VENV_DIR="$PROJECT_DIR/.venv"

log_info "======================================================================="
log_info "GOFR-IQ Container Entrypoint"
log_info "======================================================================="

ensure_dir() {
    local dir="$1"
    if [ -d "$dir" ]; then
        return 0
    fi
    mkdir -p "$dir" 2>/dev/null || sudo mkdir -p "$dir" 2>/dev/null
}

# Align docker group GID with host's docker socket GID (for DinD)
if [ -S /var/run/docker.sock ]; then
    DOCKER_SOCK_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null)
    CURRENT_DOCKER_GID=$(getent group docker | cut -d: -f3)
    if [ -n "$DOCKER_SOCK_GID" ] && [ "$DOCKER_SOCK_GID" != "$CURRENT_DOCKER_GID" ]; then
        log_info "Aligning docker group GID: $CURRENT_DOCKER_GID -> $DOCKER_SOCK_GID"
        sudo groupmod -g "$DOCKER_SOCK_GID" docker 2>/dev/null || \
            log_warn "Could not align docker GID. Docker commands may fail."
    fi
fi

# Fix data directory permissions if mounted as volume
if [ -d "$PROJECT_DIR/data" ]; then
    if [ ! -w "$PROJECT_DIR/data" ]; then
        log_warn "Data directory not writable: $PROJECT_DIR/data"
        if command -v sudo >/dev/null 2>&1; then
            log_info "Attempting to fix permissions for $PROJECT_DIR/data"
            sudo chown -R "$(id -u):$(id -g)" "$PROJECT_DIR/data" 2>/dev/null || \
                log_warn "Could not fix permissions. Run container with --user $(id -u):$(id -g)"
        else
            log_warn "sudo not available. Run container with --user $(id -u):$(id -g)"
        fi
    fi
fi

# Create subdirectories if they don't exist (best-effort)
if ! ensure_dir "$PROJECT_DIR/data/storage"; then
    log_warn "Could not create $PROJECT_DIR/data/storage"
fi
if ! ensure_dir "$PROJECT_DIR/data/auth"; then
    log_warn "Could not create $PROJECT_DIR/data/auth"
fi
if ! ensure_dir "$PROJECT_DIR/logs"; then
    log_warn "Could not create $PROJECT_DIR/logs (bind mount may be read-only for this UID/GID)"
fi

# Ensure virtual environment exists and is valid
if [ ! -f "$VENV_DIR/bin/python" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
    log_info "Creating Python virtual environment..."
    cd "$PROJECT_DIR"
    UV_VENV_CLEAR=1 uv venv "$VENV_DIR" --python=python3.11
    log_info "Virtual environment created at $VENV_DIR"
fi

# Install gofr-common as editable package
if [ -d "$COMMON_DIR" ]; then
    log_info "Installing gofr-common (editable)..."
    cd "$PROJECT_DIR"
    uv pip install -e "$COMMON_DIR"
else
    log_warn "gofr-common not found at $COMMON_DIR"
    log_warn "Initialize the submodule: git submodule update --init"
fi

# Install project dependencies
if [ -f "$PROJECT_DIR/pyproject.toml" ]; then
    log_info "Installing project dependencies from pyproject.toml..."
    cd "$PROJECT_DIR"
    uv pip install -e ".[dev]" || log_warn "Could not install project dependencies"
elif [ -f "$PROJECT_DIR/requirements.txt" ]; then
    log_info "Installing project dependencies from requirements.txt..."
    cd "$PROJECT_DIR"
    uv pip install -r requirements.txt || log_warn "Could not install project dependencies"
fi

# Show installed packages
echo ""
log_info "Environment ready. Installed packages:"
uv pip list

echo ""
log_info "======================================================================="
log_info "Entrypoint complete. Executing: $*"
log_info "======================================================================="

exec "$@"
