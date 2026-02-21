#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RUN_TESTS=false

usage() {
    echo "Usage: $0 [--tests]"
    echo ""
    echo "Idempotent bootstrap for gofr-iq so ./docker/start-prod.sh can run cleanly." 
    echo ""
    echo "Options:"
    echo "  --tests   Run ./scripts/run_tests.sh after bootstrap"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tests)
            RUN_TESTS=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            echo "" >&2
            usage >&2
            exit 2
            ;;
    esac
done

cd "${PROJECT_ROOT}"

echo "======================================================================="
echo "Bootstrap gofr-iq prerequisites"
echo "======================================================================="

GOFR_PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
if [ -f "${GOFR_PORTS_FILE}" ]; then
    set -a
    source "${GOFR_PORTS_FILE}"
    set +a
else
    echo "ERROR: Missing ports file: ${GOFR_PORTS_FILE}" >&2
    exit 1
fi

# ----------------------------------------------------------------------
# 1) Ensure submodules are present
# ----------------------------------------------------------------------
if [ -f "${PROJECT_ROOT}/.gitmodules" ]; then
    echo "Ensuring git submodules are initialized..."
    git submodule update --init --recursive
else
    echo "No .gitmodules found; skipping submodule init"
fi

# ----------------------------------------------------------------------
# 2) Ensure Vault is running, initialized, and unsealed
# ----------------------------------------------------------------------
VAULT_MANAGE_SCRIPT="${PROJECT_ROOT}/lib/gofr-common/scripts/manage_vault.sh"
SECRETS_DIR="${PROJECT_ROOT}/secrets"

VAULT_ADDR="http://gofr-vault:${GOFR_VAULT_PORT:-8201}"
export VAULT_ADDR

echo "Checking Vault health at ${VAULT_ADDR}..."
HEALTH_CODE="$(curl -s -o /dev/null -w "%{http_code}" "${VAULT_ADDR}/v1/sys/health" 2>/dev/null || echo "000")"

if [ "${HEALTH_CODE}" = "200" ] || [ "${HEALTH_CODE}" = "429" ]; then
    echo "Vault reachable and unsealed (health ${HEALTH_CODE})"
else
    echo "Vault not ready (HTTP ${HEALTH_CODE}); bootstrapping..."
    if [ ! -x "${VAULT_MANAGE_SCRIPT}" ]; then
        echo "ERROR: Vault management script not found/executable: ${VAULT_MANAGE_SCRIPT}" >&2
        exit 1
    fi

    if [ ! -f "${SECRETS_DIR}/vault_root_token" ]; then
        "${VAULT_MANAGE_SCRIPT}" bootstrap
    else
        "${VAULT_MANAGE_SCRIPT}" start
        sleep 3
        "${VAULT_MANAGE_SCRIPT}" unseal
    fi

    sleep 2
    HEALTH_CODE="$(curl -s -o /dev/null -w "%{http_code}" "${VAULT_ADDR}/v1/sys/health" 2>/dev/null || echo "000")"
    if [ "${HEALTH_CODE}" != "200" ] && [ "${HEALTH_CODE}" != "429" ]; then
        echo "ERROR: Vault still not ready after bootstrap (HTTP ${HEALTH_CODE})" >&2
        exit 1
    fi
    echo "Vault is now running and unsealed"
fi

if [ ! -f "${SECRETS_DIR}/vault_root_token" ]; then
    echo "ERROR: Missing ${SECRETS_DIR}/vault_root_token" >&2
    echo "Remediation: run ${VAULT_MANAGE_SCRIPT} bootstrap" >&2
    exit 1
fi

VAULT_TOKEN="$(cat "${SECRETS_DIR}/vault_root_token")"
export VAULT_TOKEN

# ----------------------------------------------------------------------
# 3) Ensure AppRole identities + creds exist
# ----------------------------------------------------------------------
echo "Ensuring service AppRoles..."
bash "${PROJECT_ROOT}/scripts/ensure_approle.sh"

# ----------------------------------------------------------------------
# 4) Verify core secrets exist in Vault
# ----------------------------------------------------------------------
echo "Verifying core secrets in Vault..."

get_vault_field() {
    local field="$1"
    local path="$2"
    docker exec -e VAULT_ADDR="${VAULT_ADDR}" -e VAULT_TOKEN="${VAULT_TOKEN}" \
        gofr-vault vault kv get -field="${field}" "${path}" 2>/dev/null || true
}

JWT_EXISTS="$(get_vault_field value secret/gofr/config/jwt-signing-secret)"
if [ -z "${JWT_EXISTS}" ]; then
    echo "ERROR: JWT signing secret missing in Vault at secret/gofr/config/jwt-signing-secret" >&2
    echo "Remediation: lib/gofr-common/scripts/manage_vault.sh jwt-secret" >&2
    exit 1
fi

OPENROUTER_EXISTS="$(get_vault_field value secret/gofr/config/api-keys/openrouter)"
if [ -z "${OPENROUTER_EXISTS}" ]; then
    echo "ERROR: OpenRouter API key missing in Vault at secret/gofr/config/api-keys/openrouter" >&2
    echo "Remediation: ./docker/start-prod.sh --fresh --openrouter-key <your-key>" >&2
    exit 1
fi

NEO4J_PW_EXISTS="$(get_vault_field value secret/gofr/config/neo4j-password)"
if [ -z "${NEO4J_PW_EXISTS}" ]; then
    echo "ERROR: Neo4j password missing in Vault at secret/gofr/config/neo4j-password" >&2
    echo "Remediation: ./docker/start-prod.sh --fresh" >&2
    exit 1
fi

echo "Bootstrap complete. Next: ./docker/start-prod.sh"

if [ "${RUN_TESTS}" = true ]; then
    echo ""
    echo "Running test suite (--tests)..."
    "${PROJECT_ROOT}/scripts/run_tests.sh"
fi
