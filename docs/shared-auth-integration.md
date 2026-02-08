# Shared Auth Integration (Multi‑Service)

This document is a machine‑readable guide for integrating a second GOFR service with shared auth (groups + tokens) using gofr-common. It assumes Vault is the source of truth and services run on the shared `gofr-net` network.

## Summary (must‑match invariants)

1. **Shared JWT signing secret** lives at Vault path:
   - `secret/gofr/config/jwt-signing-secret`
2. **Shared group and token registries** live at Vault path prefix:
   - `gofr/auth` (e.g., `secret/gofr/auth/groups/*`, `secret/gofr/auth/tokens/*`)
3. Every service must:
   - Use the **same Vault auth path prefix** (`GOFR_VAULT_PATH_PREFIX=gofr/auth`)
   - Use the **same JWT secret value**, but exported under its own env prefix
   - Have its **own AppRole** + Vault policy

## Required Changes (for a new service, example name: `gofr-doc`)

### 1) Add a Vault policy in gofr-common
File: `lib/gofr-common/src/gofr_common/auth/policies.py`

Add a new policy that includes the shared GOFR config + auth paths:
```
POLICY_DOC_READ = """
path "secret/data/services/doc/*" {
  capabilities = ["read"]
}
path "secret/data/tokens/doc" {
  capabilities = ["read"]
}
""" + POLICY_GLOBAL_READ + POLICY_GOFR_CONFIG_READ

POLICIES = {
    "gofr-mcp-policy": POLICY_MCP_READ,
    "gofr-web-policy": POLICY_WEB_READ,
    "gofr-doc-policy": POLICY_DOC_READ,
}
```

### 2) Add the service to AppRole provisioning
File: `scripts/setup_approle.py`

Add the service/policy pair:
```
SERVICES = {
    "gofr-mcp": "gofr-mcp-policy",
    "gofr-web": "gofr-web-policy",
    "gofr-doc": "gofr-doc-policy",
}
```

This generates:
- `secrets/service_creds/gofr-doc.json`

### 3) Ensure the service reads the shared JWT secret
Each service reads JWT from `{PREFIX}_JWT_SECRET` (e.g., `GOFR_DOC_JWT_SECRET`).

**Important:** the value must be the same as gofr-iq and must come from Vault:
```
GOFR_DOC_JWT_SECRET=$(vault kv get -field=value secret/gofr/config/jwt-signing-secret)
export GOFR_DOC_JWT_SECRET
```

### 4) Ensure Docker wiring uses shared auth path + AppRole creds
Service container must include:
- `GOFR_AUTH_BACKEND=vault`
- `GOFR_VAULT_URL=http://gofr-vault:${GOFR_VAULT_PORT}`
- `GOFR_VAULT_PATH_PREFIX=gofr/auth`
- `GOFR_VAULT_MOUNT_POINT=secret`
- Mount its AppRole file to `/run/secrets/vault_creds`

Example docker-compose snippet:
```
services:
  gofr-doc-mcp:
    environment:
      - GOFR_DOC_JWT_SECRET=${GOFR_DOC_JWT_SECRET}
      - GOFR_AUTH_BACKEND=vault
      - GOFR_VAULT_URL=http://gofr-vault:${GOFR_VAULT_PORT}
      - GOFR_VAULT_PATH_PREFIX=gofr/auth
      - GOFR_VAULT_MOUNT_POINT=secret
    volumes:
      - ${HOST_PROJECT_ROOT:-..}/lib/gofr-common/secrets/service_creds/gofr-doc.json:/run/secrets/vault_creds:ro
    networks:
      - gofr-net
```

## Handling the "secrets" Directory Scope

### Recommended approach (dev‑only)
The `secrets/` directory should be **dev‑only** and used only by management scripts
(`bootstrap`, `setup_approle`, token tools). Production services should load
everything from Vault or environment at start time.

**Do not wire secrets into prod compose.** Only bind into dev containers or use
host‑side scripts.

Recommended pattern:
- Create a shared host directory outside any repo (e.g., `/home/gofr/devroot/shared-secrets/`).
- Point management scripts to it via an env var (e.g., `GOFR_SECRETS_DIR`).
- Optionally symlink `secrets/` in each repo to that directory for convenience.

### Why this matters
If the other project keeps `secrets/` local, it will **not** see shared:
- `vault_root_token`
- `vault_unseal_key`
- `bootstrap_tokens.json`
- `service_creds/*.json`

### Minimal fix (dev)
Create the same symlink in each repo so scripts see the shared directory:
```
# From project root (dev only)
ln -s /home/gofr/devroot/shared-secrets ./secrets
```

Alternatively, export a shared directory before running scripts:
```
export GOFR_SECRETS_DIR=/home/gofr/devroot/shared-secrets
```

Then update any management script to use:
- `${GOFR_SECRETS_DIR:-$PROJECT_ROOT/secrets}`

This keeps secrets **out of repos** while still supporting dev‑time scripts.

## Runtime Flow (end‑to‑end)

1. Vault stores the shared JWT secret at `secret/gofr/config/jwt-signing-secret`.
2. Each service loads that secret into its own `{PREFIX}_JWT_SECRET` env var.
3. Each service uses the shared Vault auth path `gofr/auth`.
4. Tokens created by one service are valid across all services.
5. Group membership is shared across all services.

## Bootstrap Flow (exact sequence)

1. **Start stack**
  - Run `./scripts/start-prod.sh` (or `--fresh` for first‑time).
2. **Vault init/unseal**
  - Vault is initialized and unsealed.
  - Root token + unseal key are written to the shared secrets directory.
3. **Policies installed**
  - `bootstrap_auth.py` installs all policies from gofr-common.
4. **JWT secret generated + stored**
  - If missing, `{PREFIX}_JWT_SECRET` is generated.
  - Stored at `secret/gofr/config/jwt-signing-secret`.
5. **Reserved groups ensured**
  - `public` and `admin` groups are created in `gofr/auth`.
6. **Bootstrap tokens minted**
  - Long‑lived tokens created and saved to `secrets/bootstrap_tokens.json`.
7. **AppRole provisioning**
  - `scripts/setup_approle.py` creates AppRoles and writes:
    - `secrets/service_creds/{service}.json`
8. **Runtime secret load**
  - `start-prod.sh` reads JWT secret from Vault and exports `{PREFIX}_JWT_SECRET`.
9. **Services start**
  - Services mount `/run/secrets/vault_creds` and authenticate to Vault.
  - Auth data (groups/tokens) read from `gofr/auth`.

## Checklist (gofr-doc)

- [ ] Add `gofr-doc-policy` in `gofr_common/auth/policies.py`
- [ ] Add `gofr-doc` to `scripts/setup_approle.py`
- [ ] Run AppRole provisioning to generate `service_creds/gofr-doc.json`
- [ ] Load JWT secret from Vault into `GOFR_DOC_JWT_SECRET`
- [ ] Set `GOFR_VAULT_PATH_PREFIX=gofr/auth`
- [ ] Mount `service_creds/gofr-doc.json` into `/run/secrets/vault_creds`
- [ ] Ensure `secrets/` is symlinked to shared `lib/gofr-common/secrets`

## Notes

- **Do not create a new JWT secret.** All services must share the same value.
- **Do not use localhost** — use service hostnames (`gofr-vault`, `gofr-neo4j`, etc.).
- If using scripts, always prefer GOFR control scripts.
