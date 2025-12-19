# Auth Flow Migration Plan

## Current State Analysis

### Deep Dive: What's Actually Happening

After analyzing the codebase, here's the **actual** current auth flow:

#### 1. MCP Server (`app/main_mcp.py`)

**Current behavior:**
- Auth is **disabled by default** (`GOFR_IQ_AUTH_DISABLED=true`)
- The `AuthHeaderMiddleware` is **NOT applied** (line 178: `# TODO: Re-enable auth middleware`)
- MCP handler runs directly without middleware wrapping
- `get_permitted_groups_from_context()` returns `["public"]` because no middleware sets the context

**The TODO comment says it all:**
```python
# For now, use the handler directly without Starlette wrapping
# TODO: Re-enable auth middleware for group extraction
app = mcp_handler
```

#### 2. MCPO Server (test script vs production)

**Test script (`run_tests.sh` line 387):**
```bash
mcpo --host 0.0.0.0 --port "${GOFR_IQ_MCPO_PORT}" \
    --api-key "${GOFR_IQ_JWT_SECRET}" \   # <-- PROBLEM!
    --server-type streamable-http \
    -- "${mcp_url}"
```

**Production (`docker-compose.yml` line 121):**
```bash
mcpo --host 0.0.0.0 --port 8081 --server-type streamable-http -- http://gofr-iq-mcp:8080/mcp
```

**Problem:** Test script uses `--api-key` which makes MCPO validate tokens itself, rejecting JWTs meant for MCP.

#### 3. Web Server (`app/web_server/web_server.py`)

**Current behavior:**
- Auth is **disabled by default** (`GOFR_IQ_AUTH_DISABLED=true`)
- When enabled, uses FastAPI `Depends(verify_token)` to validate JWT
- Token validation happens via `gofr_common.auth` middleware
- Group is extracted from `token_info.groups[0]` (line 194)
- Does NOT pass JWT to MCP - **separate auth validation**

#### 4. Group Filtering in Tools

All MCP tools call `get_permitted_groups_from_context()` which:
1. Calls `gofr_common.web.get_auth_header_from_context()` to get header from ContextVar
2. But `AuthHeaderMiddleware` is disabled, so this always returns `""`
3. Returns `["public"]` for all requests (no group filtering!)

**Files using this pattern:**
- `app/tools/query_tools.py` (lines 82, 251)
- `app/tools/source_tools.py` (lines 77, 160)
- `app/tools/client_tools.py` (line 266)
- `app/tools/graph_tools.py` (line 426)

---

## Target State

### Desired Auth Flow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Client    │───▶│    MCPO     │───▶│     MCP     │
│ (with JWT)  │    │(pass-thru)  │    │(auth mode)  │
└─────────────┘    └─────────────┘    └─────────────┘
      │                  │                   │
      │                  │                   │
      ▼                  ▼                   ▼
 Authorization:     Forwards header    AuthHeaderMiddleware
 Bearer <JWT>       unchanged          stores in ContextVar
                    (no validation)          │
                                             ▼
                                    Tools call get_permitted_
                                    groups_from_context()
                                             │
                                             ▼
                                    Query results filtered
                                    by permitted groups
```

### Key Principles

1. **MCPO is transparent** - never validates JWTs, just forwards headers
2. **MCP validates tokens** - extracts groups, filters all responses
3. **Web delegates to MCP** - passes JWT header for group filtering
4. **No token = public only** - anonymous access limited to public group

---

## Migration Phases

### Phase 1: Enable AuthHeaderMiddleware in MCP Server

**Goal:** Make MCP server extract JWT from headers and set in ContextVar.

**File:** `app/main_mcp.py`

**Changes:**
```python
# Before (line 178-179):
# TODO: Re-enable auth middleware for group extraction
app = mcp_handler

# After:
from starlette.applications import Starlette
from starlette.routing import Mount
from gofr_common.web import AuthHeaderMiddleware

mcp_handler = mcp.streamable_http_app()

# Wrap with auth middleware for group extraction
app = Starlette(
    routes=[Mount("/", app=mcp_handler)],
)
app.add_middleware(AuthHeaderMiddleware)
```

**Test:**
```bash
# Start MCP with auth enabled
python -m app.main_mcp --port 8180

# Send request with JWT
curl -H "Authorization: Bearer ${JWT}" http://localhost:8180/mcp
```

**Verification:**
- Add debug logging in `get_permitted_groups_from_context()`
- Verify groups are extracted from token

---

### Phase 2: Remove `--api-key` from MCPO in Test Script

**Goal:** Make MCPO forward auth headers without validation.

**File:** `scripts/run_tests.sh`

**Changes:**
```bash
# Before (line 386-388):
nohup mcpo --host 0.0.0.0 --port "${GOFR_IQ_MCPO_PORT}" \
    --api-key "${GOFR_IQ_JWT_SECRET}" \
    --server-type streamable-http \
    -- "${mcp_url}"

# After:
nohup mcpo --host 0.0.0.0 --port "${GOFR_IQ_MCPO_PORT}" \
    --server-type streamable-http \
    -- "${mcp_url}"
```

**Test:**
```bash
# Start servers
./scripts/run_tests.sh --servers-only

# Call MCPO with JWT - should reach MCP
curl -H "Authorization: Bearer ${JWT}" \
     http://localhost:8181/query_documents \
     -d '{"query": "test"}'
```

**Verification:**
- JWT should not be rejected by MCPO
- MCP should receive the Authorization header

---

### Phase 3: Initialize GroupService with AuthService in MCP

**Goal:** Enable JWT validation in MCP tools.

**Files:**
- `app/mcp_server/mcp_server.py`
- `app/services/group_service.py`

**Changes in `mcp_server.py`:**
```python
from app.auth import AuthService
from app.services.group_service import init_group_service

def create_mcp_server(..., require_auth: bool = True):
    # ... existing code ...
    
    # Initialize auth for group filtering
    if require_auth:
        jwt_secret = os.getenv("GOFR_IQ_JWT_SECRET")
        token_store = os.getenv("GOFR_IQ_TOKEN_STORE")
        auth_service = AuthService(
            secret_key=jwt_secret,
            token_store_path=token_store,
        )
        init_group_service(auth_service=auth_service)
```

**Test:**
```bash
# Query with valid token - should return filtered results
curl -H "Authorization: Bearer ${VALID_JWT}" \
     http://localhost:8181/query_documents

# Query with no token - should return only public documents
curl http://localhost:8181/query_documents
```

---

### Phase 4: Create Integration Tests for Auth Flow

**Goal:** Verify end-to-end auth flow through MCPO → MCP.

**New File:** `test/test_auth_flow_integration.py`

```python
"""Integration tests for auth flow through MCPO → MCP."""

import pytest
from app.auth import AuthService

@pytest.fixture
def auth_service():
    """AuthService with test groups pre-created."""
    auth = AuthService(secret_key="test-secret", token_store_path=":memory:")
    auth.groups.create_group("group-a", "Test Group A")
    auth.groups.create_group("group-b", "Test Group B")
    return auth

@pytest.fixture
def token_group_a(auth_service):
    return auth_service.create_token(groups=["group-a"])

@pytest.fixture
def token_group_b(auth_service):
    return auth_service.create_token(groups=["group-b"])

class TestMCPOAuthPassthrough:
    """Test that MCPO passes auth headers to MCP."""
    
    @pytest.mark.integration
    def test_jwt_forwarded_to_mcp(self, mcpo_url, token_group_a):
        """JWT sent to MCPO should reach MCP unchanged."""
        # This requires running servers
        pass
    
    @pytest.mark.integration
    def test_no_token_gets_public_only(self, mcpo_url):
        """No token should only access public group."""
        pass

class TestMCPGroupFiltering:
    """Test that MCP filters results by token groups."""
    
    @pytest.mark.integration
    def test_query_returns_only_permitted_groups(self, mcpo_url, token_group_a):
        """Query should only return docs in token's groups + public."""
        pass
    
    @pytest.mark.integration
    def test_get_document_denied_for_other_group(self, mcpo_url, token_group_a):
        """Get document from group-b with group-a token should fail."""
        pass
```

---

### Phase 5: Update Web Server to Pass JWT to MCP

**Goal:** Web server should delegate auth to MCP, not validate separately.

**File:** `app/web_server/web_server.py`

**Current problem:** Web server validates JWT independently, then calls services directly without passing auth context.

**Options:**
1. **Option A:** Web server calls MCP tools internally (passes auth via context)
2. **Option B:** Web server calls MCP via HTTP (forwards auth header)
3. **Option C:** Web server uses same group filtering as MCP

**Recommended: Option C** - Simplest, keeps Web independent of MCP.

**Changes:**
```python
# In web_server.py, ensure group filtering uses same pattern as MCP tools

@self.app.post("/query")
async def query_documents(
    req: QueryRequest,
    token_info: TokenInfo = Depends(self._get_auth_dependency()),
):
    # Get permitted groups from token
    permitted_groups = get_permitted_groups(token_info)
    
    # Filter results by groups
    results = self.query_service.query(
        query=req.query,
        group_guids=permitted_groups,  # Pass permitted groups
    )
    return results
```

---

### Phase 6: Update Environment Defaults

**Goal:** Enable auth by default (secure defaults).

**Files:**
- `app/main_mcp.py`
- `app/main_web.py`
- `docker/docker-compose.yml`
- `scripts/run_tests.sh`

**Changes:**

```bash
# Default to auth enabled
export GOFR_IQ_AUTH_DISABLED=false  # Change from "true"
```

```python
# In main_mcp.py and main_web.py:
parser.add_argument(
    "--auth-disabled",
    action="store_true",
    default=os.environ.get("GOFR_IQ_AUTH_DISABLED", "false").lower() in ("1", "true", "yes"),
    # Changed default from "true" to "false"
)
```

---

## Test Matrix

| Test | Before | After |
|------|--------|-------|
| MCPO with JWT | Rejected by MCPO `--api-key` | Forwarded to MCP |
| MCP with JWT | Ignored (no middleware) | Groups extracted |
| Query with token | All docs returned | Only permitted groups |
| Query without token | All docs returned | Only public group |
| Get doc from other group | Returned | Access denied |

---

## Rollout Checklist

- [ ] **Phase 1:** Enable `AuthHeaderMiddleware` in MCP
  - [ ] Modify `app/main_mcp.py`
  - [ ] Test middleware captures auth header
  - [ ] Verify `get_auth_header_from_context()` returns value
  
- [ ] **Phase 2:** Remove `--api-key` from MCPO
  - [ ] Modify `scripts/run_tests.sh`
  - [ ] Test MCPO forwards headers
  - [ ] Verify no 403 errors from MCPO
  
- [ ] **Phase 3:** Initialize GroupService in MCP
  - [ ] Modify `app/mcp_server/mcp_server.py`
  - [ ] Test `get_permitted_groups_from_context()` returns token groups
  - [ ] Verify query filtering works
  
- [ ] **Phase 4:** Add integration tests
  - [ ] Create `test/test_auth_flow_integration.py`
  - [ ] Add tests for MCPO passthrough
  - [ ] Add tests for MCP group filtering
  - [ ] Run full test suite
  
- [ ] **Phase 5:** Update Web server
  - [ ] Review web server auth flow
  - [ ] Ensure consistent group filtering
  - [ ] Test web endpoints with various tokens
  
- [ ] **Phase 6:** Update defaults to secure
  - [ ] Change `GOFR_IQ_AUTH_DISABLED` default to `false`
  - [ ] Update docker-compose.yml
  - [ ] Update documentation
  - [ ] Full regression test

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing clients | High | Keep `--no-auth` flag for dev mode |
| Test flakiness | Medium | Use `:memory:` token stores for isolation |
| Performance regression | Low | JWT validation is fast (~1ms) |
| Token store conflicts | Medium | Separate token stores per server |

---

## Success Criteria

1. **MCPO test passes:** JWT sent to MCPO reaches MCP unchanged
2. **Group filtering works:** Query returns only permitted groups
3. **Anonymous access limited:** No token = public group only
4. **All existing tests pass:** No regression
5. **Code quality checks pass:** ruff, pyright, bandit all green
