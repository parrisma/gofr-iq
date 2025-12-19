# Auth Backend Migration Plan

Upgrade gofr-iq to use the new pluggable auth backend system from gofr-common.

**Goal:** Use Vault as the auth backend for all environments (dev, test, prod).

**Strategy:** Clean break - no backwards compatibility with path-based API.

**Why Vault for everything:**
- Tests and servers share the same token store (solves the 3 failing integration tests)
- Ephemeral Vault container for tests = clean state each run
- Same code path in dev/test/prod = fewer surprises
- Multi-service ready from day one

---

## Current State

### Files Using Auth

| File | Usage |
|------|-------|
| `app/auth/__init__.py` | Re-exports from gofr_common.auth |
| `app/main_mcp.py` | Creates AuthService with path args |
| `app/main_web.py` | Creates AuthService with path args |
| `app/services/group_service.py` | Uses AuthService for token validation |
| `app/web_server/web_server.py` | Uses verify_token dependency |
| `test/*.py` | Creates AuthService with `:memory:` |

### Current API (Old)

```python
auth = AuthService(
    secret_key="...",
    token_store_path="data/tokens.json",  # OLD
)
```

### New API (Target)

```python
from gofr_common.auth import (
    AuthService,
    GroupRegistry,
    create_stores_from_env,
)

token_store, group_store = create_stores_from_env()
groups = GroupRegistry(store=group_store)
auth = AuthService(
    token_store=token_store,
    group_registry=groups,
    secret_key="...",
)
```

---

## Migration Phases

### Phase 1: Environment Configuration ✅ COMPLETE

**Goal:** Define environment variables for backend selection.

**Files:**
- `scripts/gofriq.env` ✅
- `docker/docker-compose.yml` ✅

**Changes:**

1. Added to `scripts/gofriq.env`:
```bash
# Auth Backend Configuration - Vault is the default
GOFR_AUTH_BACKEND=vault

# Vault Configuration
GOFR_VAULT_URL=http://gofr-vault:8200
GOFR_VAULT_PORT=8201
GOFR_VAULT_DEV_TOKEN=gofr-dev-root-token
GOFR_VAULT_TOKEN="${GOFR_VAULT_DEV_TOKEN}"
GOFR_VAULT_PATH_PREFIX=gofr-iq
GOFR_VAULT_MOUNT_POINT=secret
```

2. Added Vault service to `docker/docker-compose.yml`:
   - Container: `gofr-iq-vault` with hostname `gofr-vault`
   - Port: `${GOFR_VAULT_PORT:-8201}:8200`
   - Dev mode with `VAULT_DEV_ROOT_TOKEN_ID`
   - Health check on vault status
   - Added vault env vars to mcp, mcpo, web services
   - Added vault dependency to all services

**Status:** Complete

---

### Phase 2: Create Auth Factory Module ✅ COMPLETE

**Goal:** Centralize auth service creation with backend selection.

**New File:** `app/auth/factory.py` ✅

Created factory module with:
- `create_stores(prefix)` - Creates TokenStore/GroupStore from environment
- `create_auth_service(secret_key, prefix, token_store, group_store)` - Creates AuthService

Updated `app/auth/__init__.py` ✅
- Re-exports `create_auth_service` and `create_stores`

**Status:** Complete

---

### Phase 3: Update MCP Server ✅ COMPLETE

**Goal:** Use factory for AuthService creation.

**File:** `app/main_mcp.py` ✅

**Changes:**
- Replaced `from gofr_common.auth import AuthService` with `from app.auth.factory import create_auth_service`
- Removed `--token-store` CLI argument (backend now from `GOFR_AUTH_BACKEND` env)
- Removed `token_store_path` resolution logic
- Replaced manual AuthService creation with `create_auth_service(secret_key=jwt_secret)`
- Updated startup logging to show backend type

**Status:** Complete

---

### Phase 4: Update Web Server ✅ COMPLETE

**Goal:** Use factory for AuthService creation.

**File:** `app/main_web.py` ✅

**Changes:**
- Replaced `from app.auth import AuthService` with `from app.auth.factory import create_auth_service`
- Removed `--token-store` CLI argument (backend now from `GOFR_AUTH_BACKEND` env)
- Removed `token_store_path` resolution logic
- Removed `token_store_path` from GofrIqWebServer init
- Replaced manual AuthService creation with `create_auth_service(secret_key=jwt_secret)`
- Updated startup banner to show backend type instead of token store path
- Removed unused `Path` import

**Status:** Complete

---

### Phase 5: Update app/auth/__init__.py ✅ COMPLETE

**Goal:** Export new backend types and factory.

**File:** `app/auth/__init__.py` ✅

**Added exports:**
- Storage Protocols: `TokenStore`, `GroupStore`
- Memory backends: `MemoryTokenStore`, `MemoryGroupStore`
- File backends: `FileTokenStore`, `FileGroupStore`
- Vault backends: `VaultConfig`, `VaultClient`, `VaultTokenStore`, `VaultGroupStore`
- Vault exceptions: `VaultError`, `VaultConnectionError`, `VaultAuthenticationError`, `VaultNotFoundError`, `VaultPermissionError`
- Factory functions: `create_token_store`, `create_group_store`, `create_stores_from_env`
- Storage exceptions: `StorageError`, `StorageUnavailableError`, `FactoryError`

**Status:** Complete

---

### Phase 6: Update GroupService ✅ COMPLETE (No Changes Needed)

**Goal:** Verify GroupService works with new AuthService.

**File:** `app/services/group_service.py`

**Analysis:**
- GroupService receives AuthService via `init_group_service(auth_service)` ✅
- Uses `auth_service.verify_token(token, require_store=False)` for stateless JWT verification ✅
- Callers (main_mcp.py, main_web.py) now create AuthService via factory ✅
- GroupService is backend-agnostic (works with any AuthService) ✅

**Status:** Complete - no code changes required

---

### Phase 7: Add Vault Infrastructure ✅ COMPLETE

**Goal:** Enable Vault container for testing and production.

**Approach:** Reuse gofr-common vault scripts (no duplication)

**gofr-common Scripts Used:**
- `lib/gofr-common/docker/infra/vault/run.sh` - Start Vault
- `lib/gofr-common/docker/infra/vault/stop.sh` - Stop Vault
- `lib/gofr-common/docker/infra/vault/Dockerfile` - Vault image
- `lib/gofr-common/docker/infra/vault/build.sh` - Build image

**Files Updated:**
- `docker/manage_infra.sh` ✅
  - Added `do_vault_start()` - calls gofr-common vault/run.sh
  - Added `do_vault_stop()` - calls gofr-common vault/stop.sh
  - Start Vault before other infrastructure
  - Added `vault` and `vault-stop` commands
  - Updated status to show Vault container

**Usage:**
```bash
# Start Vault only
./docker/manage_infra.sh vault --test

# Start all infrastructure (now includes Vault)
./docker/manage_infra.sh start --test

# Stop Vault only
./docker/manage_infra.sh vault-stop
```

**Status:** Complete

---

### Phase 8: Update Test Runner ✅ COMPLETE

**Goal:** Configure test environment for Vault auth backend.

**File:** `scripts/run_tests.sh` ✅

**Changes:**
1. Added Vault environment variables:
   - `GOFR_AUTH_BACKEND=vault`
   - `GOFR_VAULT_URL=http://gofr-vault:8200`
   - `GOFR_VAULT_TOKEN=gofr-dev-root-token`
   - `GOFR_VAULT_PATH_PREFIX=gofr-iq-test`
   - `GOFR_VAULT_MOUNT_POINT=secret`

2. Added `start_vault()` function to start Vault container

3. Updated `stop_infrastructure()` to stop Vault

4. Updated startup sequence: Vault starts first (auth backend)

5. Removed `--token-store` from server start commands

6. Removed token store file initialization

7. Updated `print_header()` to show Vault config

**Status:** Complete

---

### Phase 9: Update Test Fixtures ✅ COMPLETE

**Goal:** Add Vault-aware fixtures for tests.

**Files Updated:**

1. `test/conftest.py` ✅
   - Added `vault_auth_service` fixture (session-scoped, shared with servers)
   - Added `auth_service_isolated` fixture (function-scoped, memory backend)
   - Added `vault_config` fixture (Vault connection details)
   - Added `vault_available` fixture (health check)
   - Updated `test_env` to include Vault env vars
   - Updated `infra_available` to include Vault
   - Added `requires_vault` and `vault` pytest markers

2. `test/fixtures/test_servers.py` ✅
   - Removed `token_store_path` property
   - Updated `get_env()` to include Vault env vars

**New Fixtures:**
| Fixture | Scope | Backend | Use Case |
|---------|-------|---------|----------|
| `vault_auth_service` | session | Vault | Integration tests with servers |
| `auth_service_isolated` | function | Memory | Unit tests, isolated |

**Status:** Complete

---

### Phase 10: Integration Test with Vault ✅ COMPLETE

**Goal:** Verify end-to-end flow with Vault backend.

**New File:** `test/test_vault_integration.py` ✅

**Test Classes:**
1. `TestVaultBackend` - Core Vault functionality tests
   - `test_vault_auth_service_creates_valid_token`
   - `test_token_persistence_in_vault`
   - `test_token_revocation_in_vault`
   - `test_token_shared_between_test_and_mcpo` (KEY TEST)
   - `test_stateless_jwt_verification_works`

2. `TestVaultInfrastructure` - Infrastructure availability tests
   - `test_vault_is_running`
   - `test_vault_config_is_set`
   - `test_env_backend_is_vault`

3. `TestOriginalFailingTests` - Re-run originally failing tests
   - `test_jwt_reaches_mcp_tools_via_mcpo`

**Run with:**
```bash
./scripts/run_tests.sh -m vault
./scripts/run_tests.sh test/test_vault_integration.py
```

**Status:** Complete

---

## ✅ MIGRATION COMPLETE

All 10 phases have been implemented. The auth backend has been migrated
from file-based to Vault-based storage.

## Execution Order

```
Phase 1: Environment Configuration     [30 min]
Phase 2: Create Auth Factory Module    [30 min]
Phase 3: Update MCP Server             [30 min]
Phase 4: Update Web Server             [30 min]
Phase 5: Update app/auth/__init__.py   [15 min]
Phase 6: Update GroupService           [15 min]
Phase 7: Add Vault Infrastructure      [1 hour]
Phase 8: Update Test Runner            [30 min]
Phase 9: Update Test Fixtures          [1 hour]
Phase 10: Integration Test with Vault  [1 hour]
                                       --------
                              Total:   ~6 hours
```

---

## Validation Checklist

After each phase, verify:

- [ ] Unit tests pass: `./scripts/run_tests.sh --unit`
- [ ] No linting errors: `ruff check app/`
- [ ] No type errors: `mypy app/`

After all phases:

- [ ] Vault container starts: `docker ps | grep gofr-iq-vault`
- [ ] MCP server starts with Vault: `python -m app.main_mcp`
- [ ] Web server starts with Vault: `python -m app.main_web`
- [ ] Integration tests pass: `./scripts/run_tests.sh --with-servers`
- [ ] The 3 failing auth tests now pass:
  - [ ] `test_jwt_reaches_mcp_tools`
  - [ ] `test_full_lifecycle`
  - [ ] `test_get_document_own_group_succeeds`

---

## Rollback

If issues arise, revert to old API by:

1. Restore old imports in `app/auth/__init__.py`
2. Restore path-based AuthService in `main_mcp.py`, `main_web.py`
3. Set `GOFR_AUTH_BACKEND=file` (closest to old behavior)

---

## Future Enhancements

1. **Token caching** - Cache verified tokens to reduce Vault calls
2. **Health checks** - Add Vault connectivity to `/health` endpoint
3. **Metrics** - Track token operations for monitoring
4. **Key rotation** - Support JWT secret rotation with Vault transit
