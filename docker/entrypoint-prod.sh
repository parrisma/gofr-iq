#!/bin/bash
# =============================================================================
# gofr-iq Production Entrypoint
# Copies AppRole creds to /run/secrets/vault_creds, sets up directories,
# then drops to gofr-iq user and exec's CMD.
#
# JWT signing secret is read from Vault at runtime by JwtSecretProvider
# (no env var needed).
#
# Usage in compose.prod.yml:
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

GOFR_USER="gofr-iq"
PROJECT_DIR="/home/${GOFR_USER}"

# Role-specific creds path (set via GOFR_IQ_CREDS_ROLE env in compose)
CREDS_ROLE="${GOFR_IQ_CREDS_ROLE:-gofr-mcp}"
CREDS_SOURCE="/run/gofr-secrets/service_creds/${CREDS_ROLE}.json"
CREDS_TARGET_DIR="/run/secrets"
CREDS_TARGET="${CREDS_TARGET_DIR}/vault_creds"

# --- Directories -------------------------------------------------------------
DATA_DIR="${GOFR_IQ_DATA_DIR:-${PROJECT_DIR}/data}"
STORAGE_DIR="${GOFR_IQ_STORAGE_DIR:-${DATA_DIR}/storage}"
AUTH_DIR="${GOFR_IQ_AUTH_DIR:-${DATA_DIR}/auth}"
LOG_DIR="${GOFR_IQ_LOG_DIR:-${PROJECT_DIR}/logs}"
mkdir -p "${DATA_DIR}" "${STORAGE_DIR}" "${AUTH_DIR}" "${DATA_DIR}/sessions" "${LOG_DIR}"
chown -R "${GOFR_USER}:${GOFR_USER}" "${DATA_DIR}" "${LOG_DIR}" 2>/dev/null || true

# --- Copy AppRole credentials ------------------------------------------------
mkdir -p "${CREDS_TARGET_DIR}"
if [ -f "${CREDS_SOURCE}" ]; then
    cp "${CREDS_SOURCE}" "${CREDS_TARGET}"
    chmod 600 "${CREDS_TARGET}" 2>/dev/null || true
    chown "${GOFR_USER}:${GOFR_USER}" "${CREDS_TARGET}" 2>/dev/null || true

    # Validate JSON structure and required keys before booting the service.
    if ! python3 - "${CREDS_TARGET}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

role_id = str(data.get('role_id', '')).strip()
secret_id = str(data.get('secret_id', '')).strip()

if not role_id or not secret_id:
    raise SystemExit(1)
PY
    then
        echo "ERROR: Invalid Vault AppRole creds JSON at ${CREDS_TARGET} (missing role_id/secret_id)"
        exit 1
    fi

    # Optional live validation: if Vault is reachable, ensure login succeeds.
    VAULT_ADDR="http://gofr-vault:${GOFR_VAULT_PORT:-8201}"
    if curl -s --connect-timeout 2 --max-time 2 "${VAULT_ADDR}/v1/sys/health" >/dev/null 2>&1; then
        ROLE_ID="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(str(d.get('role_id','')).strip())" "${CREDS_TARGET}" 2>/dev/null || true)"
        SECRET_ID="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(str(d.get('secret_id','')).strip())" "${CREDS_TARGET}" 2>/dev/null || true)"
        if [ -z "${ROLE_ID}" ] || [ -z "${SECRET_ID}" ]; then
            echo "ERROR: Could not parse required keys from ${CREDS_TARGET}"
            exit 1
        fi

        http_code="$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout 2 --max-time 4 \
            -H 'Content-Type: application/json' \
            -X POST \
            -d "{\"role_id\":\"${ROLE_ID}\",\"secret_id\":\"${SECRET_ID}\"}" \
            "${VAULT_ADDR}/v1/auth/approle/login" || true)"

        if [ "${http_code}" != "200" ]; then
            echo "ERROR: Vault AppRole login failed (HTTP ${http_code}); refusing to start with broken creds"
            exit 1
        fi
    else
        echo "WARNING: Vault unreachable at ${VAULT_ADDR}; skipping live AppRole login validation"
    fi
else
    echo "WARNING: No AppRole credentials at ${CREDS_SOURCE}"
fi

if [ "$#" -eq 0 ]; then
    echo "ERROR: No command provided to entrypoint"
    exit 1
fi

cmd=("$@")

if [ "$(id -u)" -eq 0 ]; then
    cmd_quoted="$(printf '%q ' "${cmd[@]}")"
    exec su -s /bin/bash "${GOFR_USER}" -c "exec ${cmd_quoted}"
fi

exec "${cmd[@]}"
