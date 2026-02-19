#!/bin/bash
# Ensure GOFR-IQ Vault AppRole credentials exist (aligns to gofr-doc pattern).
#
# This provisions/syncs Vault AppRoles and writes credentials to:
#   secrets/service_creds/<role>.json
#
# Requirements:
# - Vault reachable at http://gofr-vault:8201 (Docker service name)
# - Vault bootstrap artifacts present under secrets/ (root token + unseal key)
# - UV environment available
#
# Usage:
#   ./scripts/ensure_approle.sh
#   ./scripts/ensure_approle.sh --check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODE="full"
if [[ "${1:-}" == "--check" ]]; then
  MODE="check"
fi

# Load project env defaults (exports GOFR_IQ_* and compatibility GOFR_* vars)
if [[ -f "${SCRIPT_DIR}/gofriq.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/gofriq.env"
fi

VAULT_ADDR="${GOFR_IQ_VAULT_URL:-${GOFR_VAULT_URL:-http://gofr-vault:8201}}"
export VAULT_ADDR
export GOFR_VAULT_URL="${VAULT_ADDR}"

SECRETS_DIR="${PROJECT_ROOT}/secrets"
ROOT_TOKEN_FILE="${SECRETS_DIR}/vault_root_token"
UNSEAL_KEY_FILE="${SECRETS_DIR}/vault_unseal_key"
CONFIG_FILE="${PROJECT_ROOT}/config/gofr_approles.json"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "ERROR: Missing AppRole config: ${CONFIG_FILE}" >&2
  exit 2
fi

if [[ ! -f "${ROOT_TOKEN_FILE}" || ! -f "${UNSEAL_KEY_FILE}" ]]; then
  echo "ERROR: Missing Vault bootstrap artifacts under ${SECRETS_DIR}" >&2
  echo "- Expected: ${ROOT_TOKEN_FILE}" >&2
  echo "- Expected: ${UNSEAL_KEY_FILE}" >&2
  echo "Remediation: bootstrap Vault via gofr-common scripts (see lib/gofr-common/scripts/manage_vault.sh)" >&2
  exit 1
fi

# Fast reachability check (do not print secrets)
HEALTH_CODE="$(curl -s -o /dev/null -w "%{http_code}" "${VAULT_ADDR}/v1/sys/health" 2>/dev/null || echo "000")"
if [[ "${HEALTH_CODE}" != "200" && "${HEALTH_CODE}" != "429" ]]; then
  echo "ERROR: Vault not reachable/unsealed at ${VAULT_ADDR} (health HTTP ${HEALTH_CODE})" >&2
  echo "Remediation: start/unseal Vault, then retry" >&2
  exit 1
fi

APPROLE_SCRIPT="${PROJECT_ROOT}/lib/gofr-common/scripts/setup_approle.py"
if [[ ! -f "${APPROLE_SCRIPT}" ]]; then
  echo "ERROR: Missing gofr-common AppRole provisioning script: ${APPROLE_SCRIPT}" >&2
  exit 2
fi

# Allow uv-run Python to import gofr-common from the vendored path.
export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/lib/gofr-common/src:${PYTHONPATH:-}"

if [[ "${MODE}" == "check" ]]; then
  uv run -- python "${APPROLE_SCRIPT}" --project-root "${PROJECT_ROOT}" --config "${CONFIG_FILE}" --check
  exit 0
fi

uv run -- python "${APPROLE_SCRIPT}" --project-root "${PROJECT_ROOT}" --config "${CONFIG_FILE}"
