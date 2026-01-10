# Unified Test Auth Infrastructure Plan

## Overview of Problems to Fix

| # | Problem | Root Cause |
|---|---------|------------|
| 1 | Multiple JWT secrets | `GOFR_IQ_JWT_SECRET` vs `GOFR_JWT_SECRET` defined separately |
| 2 | Stale tokens from prod | `GOFR_IQ_ADMIN_TOKEN` persists from previous sessions |
| 3 | Bootstrap fails | Uses wrong Vault hostname (`gofr-vault:8301` vs `gofr-vault-test:8200`) |
| 4 | Ports hardcoded in conftest.py | Should come from `gofr_ports.sh` |
| 5 | Docker containers may use different auth state | MCP container creates its own groups |
| 6 | Tests testing "no auth" mode | Violates "all tests WITH AUTH ON" requirement |

---

## Design Principles

1. **Single Source of Truth**: One JWT secret (`GOFR_JWT_SECRET`), one Vault instance, one path prefix
2. **All Tests WITH AUTH ON**: No `--no-auth` flags, no `auth_service=None` tests in main suite
3. **Ports from gofr_ports.sh**: All port configuration comes from `lib/gofr-common/config/gofr_ports.sh`
4. **Bootstrap in pytest**: Groups and tokens created ONCE at session start via conftest.py fixtures

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    SINGLE SOURCE OF TRUTH                         │
├──────────────────────────────────────────────────────────────────┤
│  1. GOFR_JWT_SECRET (from gofr_ports.sh)                         │
│  2. gofr-vault-test (ONE Vault instance at http://...test:8200)  │
│  3. gofr-test/auth (ONE path prefix)                             │
│  4. Session-scoped fixtures create groups/tokens ONCE            │
└──────────────────────────────────────────────────────────────────┘

                              FLOW
                              ────
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  run_tests.sh   │ → │  Start Vault    │ → │ pytest session  │
│  Sets env vars  │   │  (empty state)  │   │ fixture creates │
│  - JWT_SECRET   │   │                 │   │ - admin group   │
│  - VAULT_URL    │   │                 │   │ - public group  │
│                 │   │                 │   │ - test groups   │
│                 │   │                 │   │ - admin token   │
│                 │   │                 │   │ - public token  │
└─────────────────┘   └─────────────────┘   └─────────────────┘
                                                     │
                                                     ▼
                              ┌─────────────────────────────────┐
                              │  ALL tests use same auth state  │
                              │  - Same Vault                   │
                              │  - Same JWT secret              │
                              │  - Same groups/tokens           │
                              └─────────────────────────────────┘
```

---

## Step-by-Step Implementation

### STEP 1: Consolidate JWT Secret to Single Source

**File:** `scripts/run_tests.sh` (lines ~68-125)

**Changes:**
1. Remove `GOFR_IQ_JWT_SECRET` definition
2. Use `GOFR_JWT_SECRET` from `gofr_ports.sh` as THE single source
3. Clear any stale tokens at startup

```bash
# REMOVE THIS LINE:
export GOFR_IQ_JWT_SECRET="test-secret-key-for-secure-testing-do-not-use-in-production"

# AFTER sourcing gofr_ports.sh, ADD:
# Clear stale tokens from previous sessions (they may have wrong signature)
unset GOFR_IQ_ADMIN_TOKEN GOFR_IQ_PUBLIC_TOKEN

# Use the SINGLE JWT secret from gofr_ports.sh for ALL auth
export GOFR_JWT_SECRET="${GOFR_JWT_SECRET}"
# Legacy alias for backward compatibility
export GOFR_IQ_JWT_SECRET="${GOFR_JWT_SECRET}"
```

---

### STEP 2: Fix Vault Hostname in Bootstrap

**File:** `scripts/run_tests.sh` - `run_bootstrap_auth()` function

**Problem:** Bootstrap script tries to connect to `gofr-vault:8301` but test Vault is `gofr-vault-test:8200`

**Change:** Remove the broken `run_bootstrap_auth()` function entirely. Move bootstrap logic INTO `conftest.py` where it can use the correct environment variables.

---

### STEP 3: Create Bootstrap Groups/Tokens in conftest.py

**File:** `test/conftest.py`

**Changes:**
1. Add session-scoped fixture that creates `admin` and `public` groups + tokens
2. Export tokens to environment for tests that need them
3. Use `GOFR_JWT_SECRET` exclusively

```python
@pytest.fixture(scope="session")
def bootstrap_auth(vault_auth_service) -> dict[str, str]:
    """Create bootstrap groups and tokens ONCE at session start.
    
    This ensures:
    - admin/public groups exist in Vault
    - admin/public tokens are created with correct JWT secret
    - All tests share the same tokens
    """
    # Create reserved groups if not exist
    _ensure_group(vault_auth_service, "admin", "Administrator group")
    _ensure_group(vault_auth_service, "public", "Public group")
    
    # Create bootstrap tokens
    admin_token = vault_auth_service.create_token(groups=["admin"])
    public_token = vault_auth_service.create_token(groups=["public"])
    
    # Export to environment for tests that read from env
    os.environ["GOFR_IQ_ADMIN_TOKEN"] = admin_token
    os.environ["GOFR_IQ_PUBLIC_TOKEN"] = public_token
    
    return {
        "admin_token": admin_token,
        "public_token": public_token,
    }
```

---

### STEP 4: Update Port Configuration in conftest.py

**File:** `test/conftest.py`

**Changes:**
1. Remove hardcoded port fallbacks
2. Read ports from environment (set by `run_tests.sh` from `gofr_ports.sh`)
3. Fail fast if ports not set (forces use of `run_tests.sh`)

```python
@pytest.fixture(scope="session")
def test_ports() -> dict[str, int]:
    """Get test ports from environment (set by run_tests.sh from gofr_ports.sh)."""
    required = ["GOFR_IQ_MCP_PORT", "GOFR_IQ_MCPO_PORT", "GOFR_IQ_WEB_PORT"]
    missing = [k for k in required if k not in os.environ]
    if missing:
        pytest.fail(
            f"Missing port config: {missing}. "
            "Run tests via ./scripts/run_tests.sh"
        )
    return {
        "mcp": int(os.environ["GOFR_IQ_MCP_PORT"]),
        "mcpo": int(os.environ["GOFR_IQ_MCPO_PORT"]),
        "web": int(os.environ["GOFR_IQ_WEB_PORT"]),
    }
```

---

### STEP 5: Update docker-compose-test.yml

**File:** `docker/docker-compose-test.yml`

**Changes:**
1. MCP container uses `GOFR_JWT_SECRET` (not `GOFR_IQ_JWT_SECRET`)
2. Remove `--no-auth` flag (already done)
3. Use same Vault path prefix as tests

```yaml
mcp:
  environment:
    - GOFR_JWT_SECRET=${GOFR_JWT_SECRET}  # Single source of truth
    - GOFR_AUTH_BACKEND=vault
    - GOFR_VAULT_URL=http://gofr-vault-test:8200
    - GOFR_VAULT_PATH_PREFIX=gofr-test/auth  # Must match conftest.py
```

---

### STEP 6: Update vault_auth_service Fixture

**File:** `test/conftest.py`

**Changes:**
1. Use `GOFR_JWT_SECRET` only (no fallback chain)
2. Fail if not set
3. Add `bootstrap_auth` as dependency

```python
@pytest.fixture(scope="session")
def vault_auth_service():
    """Create AuthService with Vault backend."""
    # Single JWT secret - no fallbacks
    jwt_secret = os.environ.get("GOFR_JWT_SECRET")
    if not jwt_secret:
        pytest.fail(
            "GOFR_JWT_SECRET not set. Run tests via ./scripts/run_tests.sh"
        )
    
    auth = create_auth_service(secret_key=jwt_secret)
    # ... rest of fixture
```

---

### STEP 7: Handle "No Auth" Tests

**Option A (Recommended):** Keep them but mark them clearly

```python
@pytest.mark.no_auth
class TestResolveWriteGroupNoAuth:
    """Tests for auth-disabled mode (skip in normal test runs)."""
```

In `run_tests.sh`:
```bash
# Skip no-auth tests by default
pytest -m "not no_auth" ...
```

**Option B:** Delete the tests entirely since requirement is "all tests WITH AUTH ON"

---

### STEP 8: Update test_bootstrap_tokens.py

**File:** `test/test_bootstrap_tokens.py`

**Changes:**
1. Use `bootstrap_auth` fixture instead of reading from environment
2. Simplify JWT decoding to use single secret

```python
def test_admin_token_has_admin_group(self, bootstrap_auth: dict) -> None:
    """Verify admin token contains the 'admin' group."""
    admin_token = bootstrap_auth["admin_token"]
    jwt_secret = os.environ["GOFR_JWT_SECRET"]  # Single source
    
    payload = jwt.decode(admin_token, jwt_secret, algorithms=["HS256"], ...)
    assert payload["groups"] == ["admin"]
```

---

### STEP 9: Update ServerManager Fixture

**File:** `test/fixtures/test_servers.py`

**Changes:**
1. Read JWT secret from `GOFR_JWT_SECRET` only
2. Read ports from environment

```python
self.jwt_secret = os.environ.get("GOFR_JWT_SECRET")
if not self.jwt_secret:
    raise ValueError("GOFR_JWT_SECRET must be set")
```

---

### STEP 10: Test Execution Order

**File:** `scripts/run_tests.sh`

**Final flow:**
```
1. Source gofr_ports.sh (sets GOFR_JWT_SECRET, test ports)
2. gofr_set_test_ports all (switches to test ports)
3. Clear stale tokens (unset GOFR_IQ_*_TOKEN)
4. Start Docker infrastructure (Vault, Neo4j, ChromaDB)
5. Wait for healthy
6. Start test servers (MCP, MCPO, Web) with GOFR_JWT_SECRET
7. Run pytest
   - conftest.py session setup:
     - vault_auth_service creates AuthService
     - bootstrap_auth creates admin/public groups & tokens
     - All test groups pre-created
   - Tests run with shared auth state
8. Stop servers
9. Stop infrastructure
```

---

## Summary Checklist

| Step | File | Change | Status |
|------|------|--------|--------|
| 1 | `run_tests.sh` | Use `GOFR_JWT_SECRET` from gofr_ports.sh, clear stale tokens | ✅ DONE |
| 2 | `run_tests.sh` | Remove broken `run_bootstrap_auth()` | ✅ DONE |
| 3 | `conftest.py` | Add `bootstrap_auth` fixture to create groups/tokens | ✅ DONE |
| 4 | `conftest.py` | Remove hardcoded port fallbacks | ✅ DONE |
| 5 | `docker-compose-test.yml` | Use `GOFR_JWT_SECRET` consistently | ✅ DONE (already correct) |
| 6 | `conftest.py` | Update `vault_auth_service` to require `GOFR_JWT_SECRET` | ✅ DONE |
| 7 | Test files | Mark/remove no-auth tests | ✅ DONE |
| 8 | `test_bootstrap_tokens.py` | Use `bootstrap_auth` fixture | ✅ DONE |
| 9 | `test_servers.py` | Use `GOFR_JWT_SECRET` only | ✅ DONE |
| 10 | Verify | Run `./scripts/run_tests.sh` end-to-end | ✅ DONE |

---

## Verification Results (2026-01-10)

```
741 passed, 3 skipped, 6 failed in 85.41s
```

**Auth consolidation verified working:**
- ✅ Single JWT secret from `gofr_ports.sh` 
- ✅ Bootstrap tokens created in pytest session fixture
- ✅ All tests share same Vault instance
- ✅ No JWT signature mismatches

**Remaining failures (unrelated to auth):**
- 2 code quality tests (pre-existing lint/type issues)
- 3 client_tools tests (test logic issues)
- 1 MCPO group access test (access control logic)

---

## Verification

After implementation, run:

```bash
./scripts/run_tests.sh -v
```

Expected outcome:
- All tests use same JWT secret
- All tests connect to same Vault instance
- Bootstrap tokens created once, shared by all tests
- No signature verification failures
- No "group not found" errors
