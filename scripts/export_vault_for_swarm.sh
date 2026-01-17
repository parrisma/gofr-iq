#!/usr/bin/env bash
# Export required secrets from Vault for swarm deployment.
# Usage: source scripts/export_vault_for_swarm.sh

set -euo pipefail

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[WARN] Source this script: source scripts/export_vault_for_swarm.sh" >&2
fi

require_env() {
    local name="$1"
    local value="${!name:-}"
    if [[ -z "$value" ]]; then
        echo "[ERROR] $name is required" >&2
        return 1
    fi
}

fetch_secret() {
    local target_var="$1"
    local path="$2"
    local description="$3"
    local value
    if ! value=$(vault kv get -field=value "$path" 2>/dev/null); then
        echo "[ERROR] Missing $description in Vault at $path" >&2
        echo "        Set it with: vault kv put $path value=<secret>" >&2
        return 1
    fi
    printf -v "$target_var" '%s' "$value"
}

require_env VAULT_ADDR
require_env VAULT_TOKEN

fetch_secret JWT_SECRET secret/gofr/config/jwt-signing-secret "JWT signing secret"
fetch_secret NEO4J_PASSWORD secret/gofr/config/neo4j-password "Neo4j password"
fetch_secret N8N_ENCRYPTION_KEY secret/gofr/config/n8n-encryption-key "n8n encryption key"

# OpenAI key is optional; fetch if present
if OPENAI_API_KEY_VALUE=$(vault kv get -field=value secret/gofr/config/api-keys/openai 2>/dev/null); then
    export OPENAI_API_KEY="$OPENAI_API_KEY_VALUE"
fi

export JWT_SECRET
export NEO4J_PASSWORD
export N8N_ENCRYPTION_KEY

echo "[OK] Exported JWT_SECRET, NEO4J_PASSWORD, N8N_ENCRYPTION_KEY from Vault"
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    echo "[OK] Exported OPENAI_API_KEY from Vault"
fi
