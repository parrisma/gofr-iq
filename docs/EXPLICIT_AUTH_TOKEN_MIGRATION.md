# Explicit Auth Token Parameter Migration

## Problem Statement

MCPO (MCP-to-OpenAPI proxy) does not forward `Authorization` headers from client requests to the upstream MCP server. This breaks auth tests that rely on per-request JWT tokens.

**Evidence from logs:**
```
AuthHeaderMiddleware: path=/mcp has_auth=False header_preview=none
get_permitted_groups_from_context: auth_header_present=False header_len=0
get_permitted_groups_from_context: no auth header -> [public]
load_with_access_check: permitted_groups=['public']
load_with_access_check: ACCESS_DENIED - doc in group=aaaaaaaa-... but permitted=['public']
```

## Solution: Explicit Auth Token Parameters

Pass JWT tokens as explicit tool parameters instead of relying on HTTP headers.

```
┌─────────┐    POST /get_document     ┌──────────┐    MCP call_tool      ┌──────────┐
│  Test   │ ──────────────────────────▶│  MCPO    │ ───────────────────────▶│   MCP    │
│ Client  │    {guid: "...",          │  Proxy   │    {guid: "...",       │  Server  │
└─────────┘     auth_tokens: ["jwt"]}  └──────────┘     auth_tokens: [...]} └──────────┘
                    ▲                                        │
                    │                                        ▼
              Parameters ARE forwarded!          Extract groups from JWT
```

---

## Implementation Phases

### Phase 1: Create Core Helper Function ✅
**Status**: COMPLETE  
**Goal**: Add `resolve_permitted_groups()` that accepts explicit tokens  
**Risk**: None - additive only

**Files**:
- `app/services/group_service.py` - Add helper function ✅
- `test/test_group_service.py` - Unit test new function ✅

**Changes**:
- Added `resolve_permitted_groups(auth_tokens: list[str] | None = None, auth_service: AuthService | None = None) -> list[str]`
- Falls back to `get_permitted_groups_from_context()` when no tokens provided
- Added `_extract_groups_from_tokens()` internal helper
- 9 unit tests passing:
  - `test_explicit_single_token`
  - `test_explicit_multi_token`
  - `test_explicit_token_with_auth_service_param`
  - `test_explicit_token_strips_bearer_prefix`
  - `test_explicit_empty_list_falls_back_to_context`
  - `test_explicit_none_falls_back_to_context`
  - `test_explicit_invalid_token_returns_public`
  - `test_explicit_mixed_valid_invalid_tokens`
  - `test_explicit_always_includes_public`

---

### Phase 2: Update One Tool (get_document) ✅
**Status**: COMPLETE  
**Goal**: Prove the pattern works end-to-end with one tool  
**Risk**: Low - one tool only

**Files**:
- `app/tools/query_tools.py` - Added `auth_tokens` param to `get_document` ✅
- `test/test_mcpo_group_access.py` - Updated `_call_get_document` helper ✅

**Changes**:
- Added `auth_tokens: list[str] | None = None` param to `get_document`
- Changed to use `resolve_permitted_groups(auth_tokens=auth_tokens)`
- Updated test helper to pass token in request body instead of headers
- Fixed test assertion to unwrap `{"data": {...}, "status": "success"}` response
- **Test passes via MCPO!**

---

### Phase 3: Update Remaining Auth Tools ✅
**Status**: COMPLETE  
**Goal**: Apply pattern to all auth-requiring tools  
**Risk**: Medium - multiple tools

**Files**:
- `app/tools/query_tools.py` ✅
- `app/tools/ingest_tools.py` ✅
- `app/tools/source_tools.py` ✅
- `app/tools/client_tools.py` ✅
- `app/tools/graph_tools.py` ✅
- `app/services/group_service.py` - Added `resolve_write_group()` helper ✅

**Tools updated with `auth_tokens` parameter**:

| Tool | File | Auth Type |
|------|------|-----------|
| `get_document` | query_tools.py | read (resolve_permitted_groups) |
| `query_documents` | query_tools.py | read (resolve_permitted_groups) |
| `ingest_document` | ingest_tools.py | write (resolve_write_group) |
| `list_sources` | source_tools.py | read (resolve_permitted_groups) |
| `get_source` | source_tools.py | read (resolve_permitted_groups) |
| `create_source` | source_tools.py | write (resolve_write_group) |
| `create_client` | client_tools.py | write (resolve_write_group) |
| `get_client_feed` | client_tools.py | read (resolve_permitted_groups) |
| `get_stock_news` | graph_tools.py | read (resolve_permitted_groups) |

---

### Phase 4: Update All MCPO Tests ✅
**Status**: COMPLETE  
**Goal**: All MCPO group access tests use explicit tokens  
**Risk**: Low - test changes only

**Files**:
- `test/test_mcpo_group_access.py` - Updated `_call_get_document` helper ✅
- `test/test_auth_flow_integration.py` - Added `with_auth_tokens()` helper, updated 5 tests ✅

**Changes**:
- Added `with_auth_tokens(payload, token)` helper function
- Updated all MCPO test calls to pass `auth_tokens` in request body
- Removed reliance on `Authorization` headers for MCPO tests
- Updated response parsing to handle `{"data": {...}, "status": "success"}` wrapper
- All 26 MCPO-related tests pass

---

### Phase 5: Remove hello Tool References ✅
**Status**: COMPLETE  
**Goal**: Remove references to non-existent `hello` endpoint  
**Risk**: Low

**Findings**:
- No actual `hello` tool exists in the codebase
- `test_hello.py` contains basic smoke tests (imports), NOT hello tool tests
- `test_vault_integration.py` was calling `/hello` endpoint that doesn't exist

**Files updated**:
- `test/test_vault_integration.py` - Changed from `/hello` to `/list_sources` with `auth_tokens`

**Result**: All 9 vault integration tests pass

---

### Phase 6: Cleanup & Documentation ✅
**Status**: COMPLETE  
**Goal**: Remove debug logging, finalize docs  
**Risk**: None

**Files cleaned**:
- `app/services/group_service.py` - Removed `_group_logger` and all `.debug()` calls
- `lib/gofr-common/src/gofr_common/web/middleware.py` - Removed `_auth_logger` and debug log
- `app/services/document_store.py` - Removed `_doc_logger` and debug logs
- `scripts/run_tests.sh` - Changed `--log-level DEBUG` to `--log-level INFO`

**Result**: All 26 auth flow tests pass, cleaner production logs

---

## Migration Complete 🎉

All 6 phases successfully implemented:
1. ✅ Helper functions (`resolve_permitted_groups`, `resolve_write_group`)
2. ✅ get_document tool updated
3. ✅ All 9 auth-requiring tools updated
4. ✅ All MCPO tests updated (26 tests pass)
5. ✅ hello endpoint references cleaned
6. ✅ Debug logging removed

---

## Rollback Safety

Each phase is independently revertible:
- Phase 1: Delete new function
- Phase 2: Remove param from one tool
- Phase 3: Remove params from tools
- Phase 4: Revert test changes
- Phase 5: Restore hello tool if needed
- Phase 6: N/A (cleanup only)

---

## Test Validation Commands

```bash
# Phase 1: Unit test helper
./scripts/run_tests.sh test/test_group_service.py::TestResolvePermittedGroups -v

# Phase 2: Single integration test
./scripts/run_tests.sh test/test_mcpo_group_access.py::TestMCPOGetDocumentGroupAccess::test_get_document_own_group_succeeds -v

# Phase 3: All tool tests
./scripts/run_tests.sh test/test_mcp_tools.py -v

# Phase 4: All MCPO tests
./scripts/run_tests.sh test/test_mcpo_group_access.py -v

# Phase 5: Verify hello removed
./scripts/run_tests.sh -v -k "not hello"

# Full suite
./scripts/run_tests.sh
```

---

## Appendix: Function Signature

```python
def resolve_permitted_groups(
    auth_tokens: list[str] | None = None,
    auth_service: AuthService | None = None,
) -> list[str]:
    """
    Get permitted groups from explicit tokens OR context header.
    
    Priority:
    1. Explicit auth_tokens parameter (for MCPO path)
    2. Authorization header from context (for direct MCP path)
    3. Default: ["public"]
    
    Args:
        auth_tokens: List of JWT tokens to extract groups from.
                    If provided, extracts groups from all tokens.
        auth_service: Optional AuthService for token validation.
                     Falls back to global GroupService's auth_service.
    
    Returns:
        List of group IDs the caller can access. Always includes "public".
    """
```
