#!/bin/sh
# Vault Entrypoint for GOFR-IQ
# Starts Vault in dev mode and optionally runs bootstrap
#
# Dev mode features:
#   - Auto-initialized and auto-unsealed
#   - In-memory storage (data lost on restart)
#   - KV v2 secrets engine auto-enabled at 'secret/'
#   - Root token set via VAULT_DEV_ROOT_TOKEN_ID

set -e

# Colors (may not work in all environments)
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo "${BLUE}[VAULT]${NC} $1"; }
log_success() { echo "${GREEN}[VAULT]${NC} $1"; }
log_warn() { echo "${YELLOW}[VAULT]${NC} $1"; }

main() {
    echo "======================================================================="
    echo "GOFR-IQ Vault Container"
    echo "======================================================================="
    echo "Mode:       Dev (in-memory, auto-unsealed)"
    echo "Root Token: ${VAULT_DEV_ROOT_TOKEN_ID:-<default>}"
    echo "Listen:     ${VAULT_DEV_LISTEN_ADDRESS:-0.0.0.0:8200}"
    echo "======================================================================="
    
    log_info "Starting Vault server..."
    
    # Execute the original vault command
    exec vault "$@"
}

main "$@"
