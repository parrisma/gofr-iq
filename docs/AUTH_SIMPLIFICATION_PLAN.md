# Auth Simplification Plan

## Problem Statement

The current dual AUTH/NO-AUTH mode causes complexity and bugs. We need a simpler model.

## Proposed Model: Always Auth with Bootstrap Tokens

### Core Principle

**Every request uses a token. No exceptions. No anonymous access.**

The public token is just a regular token that grants access to the `public` group - nothing special about its capabilities. The only difference is the system uses it automatically when no token is provided.

### Bootstrap Tokens

At service startup, two special tokens are created via bootstrap script:

| Token | Group Access | Purpose |
|-------|--------------|---------|
| **Public Token** | `public` | Default fallback when no token provided |
| **Admin Token** | `admin-group` | Protected administrative operations |

### Request Flow

```
User Request
    │
    ▼
Has Token? ─── Yes ──► Validate token → Use token's groups
    │
    No
    │
    ▼
Use Public Token → Access public group only
```

**Key insight:** Both paths go through the same auth validation. The only difference is which token is used.

## Complete Tool Inventory

### Unrestricted Operations (No auth required)

| Tool | File | Description |
|------|------|-------------|
| `health_check` | health_tools.py | Service health status |
| `list_sources` | source_tools.py | List available sources |
| `get_source` | source_tools.py | Get source details |

### Group-Scoped Operations (Access based on token's groups)

| Tool | File | Description |
|------|------|-------------|
| `create_client` | client_tools.py | Create client in any group user has token for |
| `get_client_feed` | client_tools.py | Get feed for any group user has token for |
| `add_to_portfolio` | client_tools.py | Add to portfolio in any group user has token for |
| `add_to_watchlist` | client_tools.py | Add to watchlist in any group user has token for |
| `explore_graph` | graph_tools.py | Explore graph for groups user has token for |
| `get_market_context` | graph_tools.py | Get context for any group user has token for |
| `get_instrument_news` | graph_tools.py | Get news for any group user has token for |
| `ingest_document` | ingest_tools.py | Ingest to any group user has token for |
| `get_document` | query_tools.py | Get document from any group user has token for |
| `query_documents` | query_tools.py | Results filtered to groups user has token for |

### Admin-Only Operations (Requires admin group token)

| Tool | File | Description |
|------|------|-------------|
| `create_source` | source_tools.py | Register news source - **ADMIN ONLY** |

### Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    ACCESS CONTROL MODEL                     │
├─────────────────────────────────────────────────────────────┤
│  Unrestricted (3)     │ health_check, list_sources,         │
│                       │ get_source                          │
├───────────────────────┼─────────────────────────────────────┤
│  Group-Scoped (10)    │ All other tools - access based on   │
│                       │ groups in user's token              │
├───────────────────────┼─────────────────────────────────────┤
│  Admin-Only (1)       │ create_source                       │
└───────────────────────┴─────────────────────────────────────┘
```

## Bootstrap Script

### Purpose
- Check if public/admin groups exist, create if not
- Check if public/admin tokens exist, create if not
- Must be idempotent (safe to run multiple times)
- Available for prod use (checks env vars/args for Vault connection)

### Usage

```bash
# Before tests (ephemeral Vault, runs every time via run_tests.sh)
python scripts/bootstrap_auth.py

# Production (persistent Vault, runs once)
python scripts/bootstrap_auth.py
```

### Script Logic

```python
# scripts/bootstrap_auth.py

# 1. Connect to Vault (env vars or default localhost:8200)

# 2. Create Groups (idempotent)
# - Create "public" group if missing
# - Create "admin-group" group if missing

# 3. Create Tokens (idempotent)
# - Check/create public token for "public" group
# - Check/create admin token for "admin-group" group

# 4. Output
# - Print tokens to stdout or export to env vars
```

### Token Storage

Bootstrap tokens stored in Vault with well-known IDs (or metadata):
- `public-bootstrap` → public group token
- `admin-bootstrap` → admin group token

## Testing Requirements

### Ephemeral Vault for All Auth Tests

**CRITICAL:** All testing (unit, integration, auth) MUST use ephemeral Vault service managed by `run_tests.sh`.

- ❌ No memory backend
- ❌ No file backend  
- ✅ Vault dev server (ephemeral, in-memory)

### Test Flow (Managed by run_tests.sh)

```
1. run_tests.sh starts ephemeral Vault (docker-compose)
2. run_tests.sh runs bootstrap_auth.py (creates groups & tokens)
3. run_tests.sh exports tokens as env vars
4. run_tests.sh runs pytest (ALL tests use these tokens)
5. run_tests.sh stops Vault (data discarded)
```

### Test Infrastructure Updates

```python
# test/conftest.py

@pytest.fixture(scope="session")
def vault_service():
    """Start ephemeral Vault for test session."""
    # Start Vault dev server
    container = start_vault_dev_server()
    
    # Run bootstrap script
    run_bootstrap_script()
    
    yield vault_url
    
    # Cleanup
    container.stop()

@pytest.fixture
def public_token(vault_service):
    """Get the bootstrap public token."""
    return os.environ["GOFR_IQ_PUBLIC_TOKEN"]

@pytest.fixture  
def admin_token(vault_service):
    """Get the bootstrap admin token."""
    return os.environ["GOFR_IQ_ADMIN_TOKEN"]
```

## Code Changes Required

### Remove
- [ ] `GOFR_IQ_AUTH_DISABLED` environment variable
- [ ] `--no-auth` / `--auth-disabled` CLI flags
- [ ] `auth_service is None` checks throughout codebase
- [ ] Concept of "anonymous" users
- [ ] Memory/file auth backends for testing

### Add
- [ ] `scripts/bootstrap_auth.sh` - token creation script
- [ ] Public token fallback in `resolve_write_group()`
- [ ] Public token fallback in `resolve_permitted_groups()`
- [ ] Admin group check for `create_source`
- [ ] `GOFR_IQ_PUBLIC_TOKEN` environment variable
- [ ] `GOFR_IQ_ADMIN_TOKEN` environment variable

### Modify
- [ ] `GroupService` - load public token at init, use as fallback
- [ ] `create_source` tool - require admin group
- [ ] `test/conftest.py` - use ephemeral Vault
- [ ] `scripts/run_tests.sh` - run bootstrap before tests
- [ ] Docker compose - ensure Vault available

## Implementation Phases

### Phase 1: Bootstrap Script
1. Create `scripts/bootstrap_auth.sh`
2. Test with Vault dev server
3. Integrate with `run_tests.sh`

### Phase 2: Public Token Fallback
1. Add public token loading to GroupService
2. Update `resolve_write_group()` to use fallback
3. Update `resolve_permitted_groups()` to use fallback
4. Remove `auth_service is None` checks

### Phase 3: Admin Protection
1. Add admin check to `create_source`
2. Add admin check to future admin operations
3. Test admin-only operations

### Phase 4: Cleanup
1. Remove `--no-auth` flags
2. Remove `GOFR_IQ_AUTH_DISABLED`
3. Remove memory/file backends from tests
4. Update documentation

---

## Detailed Step-by-Step Implementation Plan

Each step is small, tests pass before AND after, new tests added as we go.

### Step 1: Create bootstrap_auth.py script

**Goal:** Python script to create public/admin groups and tokens in Vault (idempotent)

**Files to create:**
- `scripts/bootstrap_auth.py`

**Tests before:** All existing tests pass (685 tests)

**Implementation:**
```python
# scripts/bootstrap_auth.py
# - Connect to Vault
# - Ensure "public" group exists
# - Ensure "admin-group" group exists
# - Check if public-bootstrap token exists, create if not (linked to public group)
# - Check if admin-bootstrap token exists, create if not (linked to admin-group)
# - Print tokens to stdout for capture
```

**Tests after:** 
- Existing tests still pass
- Manual test: `python scripts/bootstrap_auth.py` creates groups and tokens

**Commit:** "Add bootstrap_auth.py script for public/admin group and token creation"

---

### Step 2: Add bootstrap to test infrastructure

**Goal:** Update `run_tests.sh` to manage ephemeral Vault and bootstrap tokens for ALL tests

**Files to modify:**
- `scripts/run_tests.sh` - start Vault, run bootstrap, export tokens
- `test/conftest.py` - add `public_token` and `admin_token` fixtures

**Tests before:** All existing tests pass

**Implementation:**
- In `run_tests.sh`: 
  - Ensure ephemeral Vault is started (docker-compose)
  - Run `python scripts/bootstrap_auth.py`
  - Capture output, export `GOFR_IQ_PUBLIC_TOKEN` and `GOFR_IQ_ADMIN_TOKEN`
  - Run tests (pytest)
  - Cleanup (stop Vault)
- In `conftest.py`: fixtures read from env vars

**Tests after:**
- All existing tests still pass
- New test: `test_bootstrap_tokens_exist` - verify fixtures work

**Commit:** "Integrate bootstrap_auth into run_tests.sh for all tests"

---

### Step 3: Add public_token to GroupService

**Goal:** GroupService loads and stores public token at init

**Files to modify:**
- `app/services/group_service.py` - add `public_token` property

**Tests before:** All existing tests pass

**Implementation:**
```python
class GroupService:
    def __init__(self, auth_service):
        self.auth_service = auth_service
        self.public_token = os.environ.get("GOFR_IQ_PUBLIC_TOKEN")
```

**Tests after:**
- All existing tests still pass
- New test: `test_group_service_has_public_token`

**Commit:** "Add public_token property to GroupService"

---

### Step 4: Update resolve_write_group to use public token fallback

**Goal:** When no token provided, use public token instead of returning None/PUBLIC_GROUP

**Files to modify:**
- `app/services/group_service.py` - `resolve_write_group()`

**Tests before:** All existing tests pass

**Implementation:**
```python
def resolve_write_group(auth_tokens=None):
    service = get_group_service()
    if not auth_tokens and service.public_token:
        auth_tokens = [service.public_token]
    # ... rest of validation (same path for all tokens)
```

**Tests after:**
- All existing tests still pass (behavior unchanged)
- New test: `test_resolve_write_group_uses_public_token_fallback`

**Commit:** "Use public token fallback in resolve_write_group"

---

### Step 5: Update resolve_permitted_groups to use public token fallback

**Goal:** When no token provided, use public token for read access

**Files to modify:**
- `app/services/group_service.py` - `resolve_permitted_groups()`

**Tests before:** All existing tests pass

**Implementation:**
```python
def resolve_permitted_groups(auth_tokens=None):
    service = get_group_service()
    if not auth_tokens and service.public_token:
        auth_tokens = [service.public_token]
    # ... rest of validation
```

**Tests after:**
- All existing tests still pass
- New test: `test_resolve_permitted_groups_uses_public_token_fallback`

**Commit:** "Use public token fallback in resolve_permitted_groups"

---

### Step 6: Remove auth_service is None checks from GroupService

**Goal:** Remove dual-mode logic, all paths now use tokens

**Files to modify:**
- `app/services/group_service.py` - remove `if auth_service is None` branches

**Tests before:** All existing tests pass

**Implementation:**
- Remove: `if service.auth_service is None: return PUBLIC_GROUP`
- Public token fallback now handles this case

**Tests after:**
- All existing tests still pass (same behavior via different path)
- Update tests that explicitly tested None case

**Commit:** "Remove auth_service is None checks from GroupService"

---

### Step 7: Add ADMIN_GROUP constant and is_admin helper

**Goal:** Prepare for admin-only operations

**Files to modify:**
- `app/services/group_service.py` - add constant and helper

**Tests before:** All existing tests pass

**Implementation:**
```python
ADMIN_GROUP = "admin-group"

def is_admin_group(group: str) -> bool:
    return group == ADMIN_GROUP
```

**Tests after:**
- All existing tests still pass
- New test: `test_is_admin_group`

**Commit:** "Add ADMIN_GROUP constant and is_admin helper"

---

### Step 8: Add admin check to create_source

**Goal:** create_source requires admin group token

**Files to modify:**
- `app/tools/source_tools.py` - add admin check

**Tests before:** All existing tests pass

**Implementation:**
```python
def create_source(...):
    group = resolve_write_group(auth_tokens)
    if not is_admin_group(group):
        return error_response(
            error_code="ADMIN_REQUIRED",
            message="Only administrators can create sources",
        )
    # ... rest of function
```

**Tests after:**
- Existing create_source tests may need updating
- New tests:
  - `test_create_source_requires_admin`
  - `test_create_source_rejects_non_admin`
  - `test_create_source_succeeds_with_admin`

**Commit:** "Require admin group for create_source"

---

### Step 9: Remove --no-auth flag from main_mcp.py

**Goal:** Remove CLI flag, auth is always on

**Files to modify:**
- `app/main_mcp.py` - remove `--no-auth` argument

**Tests before:** All existing tests pass

**Implementation:**
- Remove argparse argument
- Remove any logic that uses it

**Tests after:**
- All existing tests still pass
- Tests that used `--no-auth` updated to use public token instead

**Commit:** "Remove --no-auth CLI flag from MCP server"

---

### Step 10: Remove GOFR_IQ_AUTH_DISABLED environment variable

**Goal:** Remove env var, auth is always on

**Files to modify:**
- `app/services/group_service.py` - remove env var check
- `app/main_mcp.py` - remove env var check
- `docker/docker-compose.yml` - remove env var
- `scripts/gofriq.env` - remove env var

**Tests before:** All existing tests pass

**Implementation:**
- Remove all references to `GOFR_IQ_AUTH_DISABLED`

**Tests after:**
- All existing tests still pass
- Tests that set this env var updated

**Commit:** "Remove GOFR_IQ_AUTH_DISABLED environment variable"

---

### Step 11: Update docker-compose for always-auth

**Goal:** Docker setup uses bootstrap tokens

**Files to modify:**
- `docker/docker-compose.yml` - ensure bootstrap runs
- `docker/entrypoint-dev.sh` - run bootstrap on start

**Tests before:** All existing tests pass

**Implementation:**
- Add bootstrap step to entrypoint
- Export tokens as env vars for services

**Tests after:**
- Docker compose up works with auth
- Services accessible with public token

**Commit:** "Update Docker setup for always-auth model"

---

### Step 12: Update demo loader to use tokens

**Goal:** Demo loader works with new auth model

**Files to modify:**
- `demo/load_demo_data.py` - use admin token for sources

**Tests before:** All existing tests pass

**Implementation:**
- Get admin token from env
- Pass to create_source calls

**Tests after:**
- Demo loader works end-to-end

**Commit:** "Update demo loader for always-auth model"

---

### Step 13: Clean up old auth test files

**Goal:** Remove tests for removed functionality

**Files to modify/remove:**
- `test/test_group_service_auth.py` - update or remove no-auth tests
- `test/test_source_tools_auth.py` - update for admin-only

**Tests before:** All tests pass

**Implementation:**
- Remove tests for `auth_service is None` 
- Remove tests for `--no-auth` flag
- Update tests to use public/admin tokens

**Tests after:**
- All remaining tests pass
- No dead test code

**Commit:** "Clean up auth tests for always-auth model"

---

### Step 14: Update documentation

**Goal:** Docs reflect new auth model

**Files to modify:**
- `docs/AUTH_SIMPLIFICATION_PLAN.md` - mark complete
- `README.md` - update auth section
- `docs/DOCKER_SETUP_GUIDE.md` - update for tokens

**Tests before:** All tests pass

**Tests after:** All tests pass

**Commit:** "Update documentation for always-auth model"

---

### Step 15: Comprehensive code review and cleanup

**Goal:** Review entire codebase for simplification opportunities after refactor

**Files to review:**
- All `app/services/*.py` - auth-related services
- All `app/tools/*.py` - tool implementations
- All `test/test_*auth*.py` - auth test files
- `app/main_*.py` - server entry points
- `scripts/` - all scripts

**Tests before:** All tests pass

**Review checklist:**
1. **Dead code** - Remove any unused functions, imports, or variables
2. **Duplicate logic** - Consolidate repeated patterns
3. **Error handling** - Ensure consistent error messages and codes
4. **Code clarity** - Simplify complex conditionals, improve naming
5. **Test coverage** - Identify gaps in auth test coverage
6. **Documentation** - Ensure docstrings match new behavior
7. **Configuration** - Remove unused env vars and CLI flags
8. **Dependencies** - Remove any unused auth-related dependencies

**Deliverable:** Create `docs/AUTH_REFACTOR_REVIEW.md` with:
- Issues found
- Proposed remediations
- Priority ranking
- Estimated effort

**Tests after:** All tests still pass

**Commit:** "Auth refactor: comprehensive code review and remediation plan"

---

## Progress Tracker

| Step | Description | Status | Tests |
|------|-------------|--------|-------|
| 1 | Create bootstrap_auth.py | ⏳ | - |
| 2 | Add bootstrap to test infra | ⏳ | - |
| 3 | Add public_token to GroupService | ⏳ | - |
| 4 | resolve_write_group fallback | ⏳ | - |
| 5 | resolve_permitted_groups fallback | ⏳ | - |
| 6 | Remove auth_service is None checks | ⏳ | - |
| 7 | Add ADMIN_GROUP and helper | ⏳ | - |
| 8 | Admin check in create_source | ⏳ | - |
| 9 | Remove --no-auth flag | ⏳ | - |
| 10 | Remove AUTH_DISABLED env var | ⏳ | - |
| 11 | Update docker-compose | ⏳ | - |
| 12 | Update demo loader | ⏳ | - |
| 13 | Clean up old tests | ⏳ | - |
| 14 | Update documentation | ⏳ | - |
| 15 | Code review & cleanup | ⏳ | - |

## Notes / Discussion

_Space for refinements based on discussion_

---

**Status:** DRAFT - Detailed plan ready for review
**Last Updated:** 2024-12-19
