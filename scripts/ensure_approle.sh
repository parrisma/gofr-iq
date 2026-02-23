#!/bin/bash
# =============================================================================
# Ensure gofr-iq Vault AppRole credentials + policies are current
# =============================================================================
# Self-healing behavior:
#   - If creds exist and validate: syncs policies only (no cred regen)
#   - If creds missing or stale: full provision (policies + roles + new creds)
#
# Policy changes in gofr-common are applied on every run -- no manual
# reprovision needed.
#
# Exit codes:
#   0 -- credentials exist and policies are synced
#   1 -- cannot provision (Vault not available, not unsealed, etc.)
#
# Usage:
#   ./scripts/ensure_approle.sh          # Sync policies; provision creds if needed
#   ./scripts/ensure_approle.sh --check  # Check only, don't provision or sync
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load project env defaults
if [[ -f "${SCRIPT_DIR}/project.env" ]]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/project.env"
fi

# Source port config (single source of truth)
_PORTS_ENV="$PROJECT_ROOT/lib/gofr-common/config/gofr_ports.env"
if [ -f "$_PORTS_ENV" ]; then
    # shellcheck source=/dev/null
    source "$_PORTS_ENV"
fi
unset _PORTS_ENV

VAULT_ADDR="${GOFR_IQ_VAULT_URL:-${GOFR_VAULT_URL:-http://gofr-vault:${GOFR_VAULT_PORT:-8201}}}"
export VAULT_ADDR
export GOFR_VAULT_URL="${VAULT_ADDR}"

SECRETS_DIR="${PROJECT_ROOT}/secrets"
FALLBACK_SECRETS_DIR="${PROJECT_ROOT}/lib/gofr-common/secrets"
CONFIG_FILE="${PROJECT_ROOT}/config/gofr_approles.json"
ROOT_TOKEN_FILE=""

# Expected creds files (3 roles for gofr-iq)
ROLES=("gofr-mcp" "gofr-web" "gofr-admin-control")

CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

# ---- Helpers ----------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
warn()  { echo "[WARN]  $*"; }
err()   { echo "[FAIL]  $*" >&2; }

# ---- Check config exists ----------------------------------------------------
if [[ ! -f "${CONFIG_FILE}" ]]; then
    err "Missing AppRole config: ${CONFIG_FILE}"
    exit 2
fi

# ---- Determine creds presence -----------------------------------------------
creds_file_for_role() {
    local role="$1"
    if [ -f "${SECRETS_DIR}/service_creds/${role}.json" ]; then
        echo "${SECRETS_DIR}/service_creds/${role}.json"
    elif [ -f "${FALLBACK_SECRETS_DIR}/service_creds/${role}.json" ]; then
        echo "${FALLBACK_SECRETS_DIR}/service_creds/${role}.json"
    fi
}

CREDS_PRESENT=true
for role in "${ROLES[@]}"; do
    if [ -z "$(creds_file_for_role "$role")" ]; then
        CREDS_PRESENT=false
        break
    fi
done

if [ "$CHECK_ONLY" = true ]; then
    if [ "$CREDS_PRESENT" = true ]; then
        ok "AppRole credentials exist for all roles"
        exit 0
    else
        warn "AppRole credentials missing for one or more roles"
        exit 1
    fi
fi

# ---- Vault reachable? -------------------------------------------------------
VAULT_STATUS=$(curl -s --connect-timeout 3 --max-time 5 "${VAULT_ADDR}/v1/sys/health" 2>/dev/null || true)

if [ -z "${VAULT_STATUS}" ]; then
    err "Vault is not reachable at ${VAULT_ADDR}."
    err "  Start it:  ./lib/gofr-common/scripts/manage_vault.sh start"
    exit 1
fi

# ---- Vault unsealed? --------------------------------------------------------
IS_SEALED=$(echo "${VAULT_STATUS}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sealed', True))" 2>/dev/null || echo "True")

if [ "$IS_SEALED" != "False" ]; then
    err "Vault is sealed."
    err "  Unseal it: ./lib/gofr-common/scripts/manage_vault.sh unseal"
    exit 1
fi

ok "Vault is running and unsealed"

# ---- Root token available? --------------------------------------------------
if [ -f "${SECRETS_DIR}/vault_root_token" ]; then
    ROOT_TOKEN_FILE="${SECRETS_DIR}/vault_root_token"
elif [ -f "${FALLBACK_SECRETS_DIR}/vault_root_token" ]; then
    ROOT_TOKEN_FILE="${FALLBACK_SECRETS_DIR}/vault_root_token"
fi

if [ -z "$ROOT_TOKEN_FILE" ]; then
    err "Vault root token not found at:"
    err "  ${SECRETS_DIR}/vault_root_token"
    err "  ${FALLBACK_SECRETS_DIR}/vault_root_token"
    err "  Bootstrap Vault first: ./lib/gofr-common/scripts/manage_vault.sh bootstrap"
    exit 1
fi

VAULT_ROOT_TOKEN=$(cat "$ROOT_TOKEN_FILE")
if [ -z "$VAULT_ROOT_TOKEN" ]; then
    err "Vault root token file is empty: $ROOT_TOKEN_FILE"
    exit 1
fi

ok "Root token found"

export GOFR_VAULT_TOKEN="$VAULT_ROOT_TOKEN"

cd "$PROJECT_ROOT"

# ---- Validate existing creds if present -------------------------------------
if [ "$CREDS_PRESENT" = true ]; then
    validate_creds_file() {
        local creds_path="$1"
        local role_id secret_id login_resp

        if [ ! -f "$creds_path" ]; then
            return 1
        fi

        role_id=$(python3 -c "import json; print(json.load(open('$creds_path'))['role_id'])" 2>/dev/null || true)
        secret_id=$(python3 -c "import json; print(json.load(open('$creds_path'))['secret_id'])" 2>/dev/null || true)
        if [ -z "$role_id" ] || [ -z "$secret_id" ]; then
            return 1
        fi

        login_resp=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST -d "{\"role_id\":\"$role_id\",\"secret_id\":\"$secret_id\"}" \
            "${VAULT_ADDR}/v1/auth/approle/login" 2>/dev/null || echo "000")
        [ "$login_resp" = "200" ]
    }

    ALL_VALID=true
    for role in "${ROLES[@]}"; do
        creds_path="$(creds_file_for_role "$role")"
        if validate_creds_file "$creds_path"; then
            info "Validated $role OK"
        else
            warn "Credential validation failed for $role"
            ALL_VALID=false
        fi
    done

    if [ "$ALL_VALID" = true ]; then
        info "All AppRole credentials validated OK"
    else
        warn "One or more AppRole credential files are invalid -- will re-provision"
        for role in "${ROLES[@]}"; do
            rm -f "${SECRETS_DIR}/service_creds/${role}.json" \
                  "${FALLBACK_SECRETS_DIR}/service_creds/${role}.json" 2>/dev/null || true
        done
        CREDS_PRESENT=false
    fi
fi

# ---- Provision / Sync -------------------------------------------------------
APPROLE_SCRIPT="${PROJECT_ROOT}/lib/gofr-common/scripts/setup_approle.py"
if [[ ! -f "${APPROLE_SCRIPT}" ]]; then
    err "Missing gofr-common AppRole provisioning script: ${APPROLE_SCRIPT}"
    exit 2
fi

# Allow uv-run Python to import gofr-common from the vendored path.
export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/lib/gofr-common/src:${PYTHONPATH:-}"

if [ "$CREDS_PRESENT" = true ]; then
    # Self-healing: sync policies & roles without regenerating credentials
    info "Syncing Vault policies (credentials already exist)..."
    uv run -- python "${APPROLE_SCRIPT}" \
        --project-root "$PROJECT_ROOT" \
        --config "${CONFIG_FILE}" \
        --policies-only
    ok "Policies synced"
    exit 0
fi

# Full provision -- creds are missing or invalid
info "Provisioning gofr-iq AppRoles (full)..."
uv run -- python "${APPROLE_SCRIPT}" \
    --project-root "$PROJECT_ROOT" \
    --config "${CONFIG_FILE}"

# ---- Verify -----------------------------------------------------------------
PROVISION_OK=true
for role in "${ROLES[@]}"; do
    if [ -z "$(creds_file_for_role "$role")" ]; then
        err "Credential file not created for role: $role"
        PROVISION_OK=false
    else
        ok "AppRole credentials provisioned: $role"
    fi
done

if [ "$PROVISION_OK" = false ]; then
    err "Provisioning completed but one or more credential files are missing"
    exit 1
fi

exit 0
