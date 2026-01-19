# Simplified Zero-Trust Secrets Architecture

## Core Principles

1.  **Minimal File Secrets**: The `secrets/` directory is the ONLY place for file-based secrets. It should contain only what is strictly necessary to bootstrap Vault or for local development overrides (if absolutely needed).
    *   `secrets/vault_root_token` (0600)
    *   `secrets/vault_unseal_key` (0600)
    *   `secrets/service_creds/*.json` (0600) - AppRole credentials for services.

2.  **Vault as Single Source of Truth**: All application configuration secrets (API keys, DB passwords, JWT secrets) live in Vault.

3.  **AppRole for Services**: Services (MCP, Web, etc.) authenticate to Vault using AppRole. The Role ID and Secret ID are provisioned into `secrets/service_creds/` by the bootstrap process and mounted into containers. They do NOT use tokens passed via environment variables.

4.  **Identity-Based Access for Scripts**: Control scripts (like `manage_document.sh`) should use their own identity or a developer identity to access Vault, rather than sharing the root token or hardcoded credentials. Ideally, they request a token or use a stored locally authenticated token (like `~/.vault-token` or a specific location in `secrets/`).

5.  **Centralized Logic in `gofr-common`**: All Vault interaction logic (bootstrapping, unsealing, client creation) resides in `gofr-common`. Scripts should call into this library rather than re-implementing logic or inlining Python code.

## Operational Contracts (keep it simple)

- **Permissions**: `secrets/` is `0700`; every file inside is `0600`.
- **No hardcoded URLs**: `start-prod.sh` reads Vault address/ports from the generated config (no inline defaults). All checks/unseal happen in Python (`scripts/bootstrap.py`).
- **Idempotent bootstrap**: `scripts/bootstrap.py` may be run repeatedly; it never re-initializes an already-initialized Vault, and it cleanly handles sealed/unsealed states. Non-zero exit on failure.
- **Single script identity**: Control scripts get a token from one place only (e.g., `secrets/dev_token` or `~/.vault-token`) via a helper in `gofr-common`; never reuse root.

## Implementation Plan

### 1. Centralized Vault Client (`gofr-common`)
*   **Module**: `gofr_common.vault`
*   **Responsibility**:
    *   Initialize/Unseal Vault.
    *   Manage AppRoles.
    *   Provide a standardized `get_client()` method.
    *   Handle retry logic and health checks.

### 2. Simplified Bootstrap (`scripts/bootstrap.py`)
*   **Role**: The orchestrator.
*   **Flow**:
    1.  Wait for Vault to be healthy.
    2.  If uninitialized -> Initialize & Unseal -> Save root token/key to `secrets/`.
    3.  If sealed -> Load key from `secrets/` -> Unseal.
    4.  Ensure `gofr-iq` secrets engine and paths exist.
    5.  Provision AppRoles for services -> Save credentials to `secrets/service_creds/`.
    6.  Generate/Rotate secrets in Vault (if needed).

### 3. Startup Script (`docker/start-prod.sh`)
*   **Role**: Simple process manager.
*   **Flow**:
    1.  Start Vault container.
    2.  Run `scripts/bootstrap.py` (Let Python handle the complexity of checking/waiting/unsealing using the common library).
    3.  Start remaining services (which mount `secrets/service_creds`).
*   **Change**: Remove the complex inline Bash/Python unseal logic. Just call the bootstrap script. The bootstrap script should be idempotent and robust enough to handle "ensure unsealed".

### 4. Service Authentication
*   **Mechanism**: AppRole.
*   **Config**: Services look for `GOFR_VAULT_ROLE_ID` and `GOFR_VAULT_SECRET_ID` (or a file path to them).
*   **Mounts**: `secrets/service_creds/gofr-mcp.json` -> `/run/secrets/vault_creds`.

### Runtime Contract (services)
- Mount exactly one file at `/run/secrets/vault_creds` with JSON shape: `{ "role_id": "...", "secret_id": "..." }`.
- Services authenticate via AppRole to fetch all other secrets from Vault; no env var fallbacks.

## Secrets Directory Structure
```
secrets/
├── vault_root_token      # Configured by bootstrap
├── vault_unseal_key      # Configured by bootstrap
└── service_creds/
    ├── gofr-mcp.json     # { "role_id": "...", "secret_id": "..." }
    └── gofr-web.json     # { "role_id": "...", "secret_id": "..." }
```

## Migration Steps to Simplify

1.  **Refactor `start-prod.sh`**:
    *   Remove `ensure_vault_unsealed` bash function.
    *   Remove inline Python.
    *   Trust `uv run scripts/bootstrap.py` to handle the unsealing and readiness check.

2.  **Enhance `scripts/bootstrap.py`**:
    *   Ensure it can be run repeatedly without error (idempotent).
    *   Ensure it handles the "unseal only" case gracefully.
    *   Use `gofr_common.vault` for all heavy lifting.

3.  **Clean up `gofr-common`**:
    *   Ensure `VaultBootstrap` is robust and minimal.

This approach reduces `start-prod.sh` to a simple orchestrator and moves the complexity into testable, managed Python code in `gofr-common` and `bootstrap.py`.
