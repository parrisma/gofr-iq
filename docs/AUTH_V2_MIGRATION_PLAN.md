# gofr-iq Auth v2 Migration Plan (Clean Cut)

## Overview

Migration from gofr_common.auth v1 (single group) to v2 (multi-group).

**Strategy:** 100% cut-over, no backward compatibility layer.

---

## Files to Modify

| File | Changes | Tests |
|------|---------|-------|
| `app/auth/__init__.py` | ✅ DONE - New exports | - |
| `app/auth/group_access.py` | `.group` → `.groups[0]` | test_group_access.py |
| `app/services/group_service.py` | Multi-group support | test_group_service.py (create) |
| `app/web_server/web_server.py` | `.group` → `.groups` | test_web_server.py |
| `test/test_mcpo_group_access.py` | `group=` → `groups=[]` | Self |
| `test/test_integration_full_lifecycle.py` | `group=` → `groups=[]` | Self |
| `docs/AUTH_ARCHITECTURE.md` | Update examples | - |

---

## Phase 1: Core Service - `group_service.py`

**File:** `app/services/group_service.py`

**Changes:**
- `token_info.group` → `token_info.groups[0]` (primary group)
- `get_permitted_groups()` → return all token groups + public
- Use `token_info.has_group()` helpers where appropriate

**Test:** Create `test/test_group_service.py` with unit tests

**Verification:**
```bash
pytest test/test_group_service.py -v
```

---

## Phase 2: Access Control - `group_access.py`

**File:** `app/auth/group_access.py`

**Changes:**
- `extract_groups_from_token()` use `.groups`
- `GroupClaims.primary_group` = `groups[0]`
- Update permission checks

**Test:** Update `test/test_group_access.py`

**Verification:**
```bash
pytest test/test_group_access.py -v
```

---

## Phase 3: Web Server - `web_server.py`

**File:** `app/web_server/web_server.py`

**Changes:**
- Line 194: `token_info.group` → `token_info.groups[0]`

**Test:** Existing web server tests

**Verification:**
```bash
pytest test/test_web*.py -v
```

---

## Phase 4: Test Files

**Files:**
- `test/test_mcpo_group_access.py`: `create_token(group=X)` → `create_token(groups=[X])`
- `test/test_integration_full_lifecycle.py`: Same pattern

**Verification:**
```bash
pytest test/test_mcpo_group_access.py test/test_integration_full_lifecycle.py -v
```

---

## Phase 5: Bootstrap & Docs ✅

**Status:** Complete

**Note:** Reserved groups (`public`, `admin`) are auto-bootstrapped when `AuthService` is initialized.
No separate init script required.

**Documentation Updated:**
- `docs/AUTH_ARCHITECTURE.md` - Updated for v2 API (multi-group tokens, group registry, etc.)

---

## Phase 6: Final Verification

**Actions:**
1. Lint check:
   ```bash
   ruff check app test scripts
   ```
2. Type check:
   ```bash
   pyright app test scripts
   ```
3. Full test suite:
   ```bash
   ./scripts/run_tests.sh
   ```

---

## API Changes Reference

### Token Creation
```python
# OLD (v1)
token = auth.create_token(group="admin")

# NEW (v2)
token = auth.create_token(groups=["admin"])
```

### Token Info Access
```python
# OLD (v1)
info.group  # str

# NEW (v2)
info.groups  # list[str]
info.groups[0]  # primary group
info.has_group("admin")  # check membership
info.has_any_group(["admin", "editors"])
info.has_all_groups(["verified", "premium"])
```

### New Exports from gofr_common.auth
```python
from gofr_common.auth import (
    # Service
    AuthService,
    InvalidGroupError,
    TokenNotFoundError,
    TokenRevokedError,
    # Tokens
    TokenInfo,
    TokenRecord,
    # Groups
    Group,
    GroupRegistry,
    RESERVED_GROUPS,
    # Middleware
    require_admin,
    require_group,
    require_any_group,
    require_all_groups,
)
```

---

## Progress Tracking

- [x] Phase 0: Update `app/auth/__init__.py` exports
- [x] Phase 1: Update `app/services/group_service.py` ✅ 27 tests
- [x] Phase 2: Update `app/auth/group_access.py` ✅ 24 tests
- [x] Phase 3: Update `app/web_server/web_server.py` ✅ 1 line
- [x] Phase 4: Update test files ✅ All tests pass
- [x] Phase 5: Bootstrap & Docs ✅ AUTH_ARCHITECTURE.md updated- [x] Phase 6: Final Verification ✅ All checks pass

## Final Verification Results (2025-12-15)

- **ruff**: All checks passed ✅
- **pyright**: 0 errors, 0 warnings ✅
- **bandit**: No security issues ✅
- **Unit tests**: 585 passed, 65 skipped ✅