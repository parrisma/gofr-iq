#!/bin/bash
# =============================================================================
# gofr-iq Production Entrypoint
# Copies AppRole creds to /run/secrets/vault_creds, sets up directories,
# then drops to gofr-iq user and exec's CMD.
#
# JWT signing secret is read from Vault at runtime by JwtSecretProvider
# (no env var needed).
#
# Usage in docker-compose.yml:
#   user: root
#   entrypoint: ["/home/gofr-iq/entrypoint-prod.sh"]
#   command:
#     - /home/gofr-iq/.venv/bin/python
#     - -m
#     - app.main_mcp
#     - ...
#
# Environment variables:
#   GOFR_IQ_VAULT_URL        - Vault address
#   GOFR_IQ_DATA_DIR         - Data root (default: /home/gofr-iq/data)
#   GOFR_IQ_STORAGE_DIR      - Storage dir (default: /home/gofr-iq/data/storage)
#   GOFR_IQ_AUTH_DISABLED    - Set to "true" to disable authentication
# =============================================================================
set -e

CREDS_SOURCE="/run/gofr-secrets/vault_creds"
CREDS_TARGET="/run/secrets/vault_creds"

# --- Directories -------------------------------------------------------------
DATA_DIR="${GOFR_IQ_DATA_DIR:-/home/gofr-iq/data}"
STORAGE_DIR="${GOFR_IQ_STORAGE_DIR:-/home/gofr-iq/data/storage}"
AUTH_DIR="${GOFR_IQ_AUTH_DIR:-/home/gofr-iq/data/auth}"
mkdir -p "${DATA_DIR}" "${STORAGE_DIR}" "${AUTH_DIR}" /home/gofr-iq/data/sessions /home/gofr-iq/logs
chown -R gofr-iq:gofr-iq /home/gofr-iq/data /home/gofr-iq/logs 2>/dev/null || true

# --- Copy AppRole credentials ------------------------------------------------
mkdir -p /run/secrets
if [ -f "${CREDS_SOURCE}" ]; then
    cp "${CREDS_SOURCE}" "${CREDS_TARGET}"
    chown gofr-iq:gofr-iq "${CREDS_TARGET}"
else
    echo "WARNING: No AppRole credentials at ${CREDS_SOURCE}"
fi

# --- Exec the service command ------------------------------------------------
# Drop to gofr-iq user and exec the CMD passed by compose
exec su -s /bin/bash gofr-iq -c "exec $*"
