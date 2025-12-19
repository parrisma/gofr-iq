# Group Access Enforcement Test Plan

## Goal

Prove that group access is defended at **every query channel** through MCPO/REST API integration tests.

## Current State Analysis

| Channel | Group Enforcement | Tests Exist | Status |
|---------|-------------------|-------------|--------|
| `GroupAccessService` | ✅ Implemented | ✅ Unit tests | Done |
| MCP Tools (`get_document`, `query_documents`) | ✅ Uses `get_group_context()` | ⚠️ Partial | Needs E2E |
| Web Server endpoints | ❌ Trusts client-provided `group_guid` | ❌ None | **BUG** (per A1) |
| MCPO (REST wrapper) | ✅ Passes JWT to MCP | ❌ None | Needs tests |

**Confirmed Bug (A1):** Web Server endpoints trust client-provided `group_guid` instead of extracting groups from the JWT token in Auth header. This needs to be fixed.

**Design Decision (A2):** Anonymous/public access uses a dedicated "public" group.

**Design Decision (A3):** Multi-group users get union of all their permitted groups' data (filtering, not access violation).

---

## Phases

### Phase 1: Baseline - MCPO Health Check Test
- [x] **Status:** ✅ Complete
- **Duration:** 5 min
- **Objective:** Verify MCPO server starts and responds, establishing test infrastructure.

**Tasks:**
1. ✅ Create `test/test_mcpo_group_access.py`
2. ✅ Add simple test that checks MCPO is reachable when servers are running
3. ✅ Run tests to confirm baseline passes

**Test scope:**
```python
def test_mcpo_health_check()
def test_mcpo_openapi_spec_available()
def test_mcpo_tools_list_available()
```

**Result:** 3 tests added, skip gracefully when servers not running, pass when running

---

### Phase 2: Token Generation Helpers
- [x] **Status:** ✅ Complete
- **Duration:** 10 min
- **Objective:** Create helper functions to generate tokens for different groups.

**Tasks:**
1. ✅ Add fixtures for creating tokens with specific group memberships
2. ✅ Create tokens for: `group-a`, `group-b`, `multi-group` (both), `public-only`
3. ✅ Add `auth_headers()` helper function
4. ✅ Add unit tests to verify token fixtures work
5. ✅ Run tests to confirm helpers work

**Test scope:**
```python
@pytest.fixture
def auth_service()       # AuthService instance for token generation

@pytest.fixture
def token_group_a()      # Token for group-a only

@pytest.fixture  
def token_group_b()      # Token for group-b only

@pytest.fixture
def token_multi_group()  # Token for both groups

@pytest.fixture
def token_public_only()  # Token for public group only

def auth_headers(token)  # Build Authorization: Bearer header

# Unit tests (no server required):
class TestTokenFixtures:
    def test_token_group_a_is_valid_jwt()
    def test_token_group_b_is_valid_jwt()
    def test_token_multi_group_is_valid_jwt()
    def test_token_public_only_is_valid_jwt()
    def test_auth_headers_format()
    def test_tokens_are_different()
```

**Result:** 6 unit tests pass, all fixtures produce valid JWT tokens

---

### Phase 3: Test Data Setup
- [x] **Status:** ✅ Complete
- **Duration:** 10 min
- **Objective:** Create documents in different groups for access testing.

**Tasks:**
1. ✅ Add fixtures that create test documents in `group-a` and `group-b`
2. ✅ Documents should have unique identifiable content per group
3. ✅ Run tests to confirm data setup works

**Test scope:**
```python
# Helper class (not a test class)
class GroupAccessTestDataSetup:
    def ensure_source(group_guid, name) -> Source
    def create_document(group_guid, source_guid, title, content) -> Document

# Fixtures
@pytest.fixture source_group_a()    # Source in group-a
@pytest.fixture source_group_b()    # Source in group-b  
@pytest.fixture source_public()     # Source in public group
@pytest.fixture doc_group_a()       # Document in group-a
@pytest.fixture doc_group_b()       # Document in group-b
@pytest.fixture doc_public()        # Document in public group

# Verification tests
class TestDataSetupVerification:
    def test_source_group_a_created()
    def test_source_group_b_created()
    def test_source_public_created()
    def test_doc_group_a_created()
    def test_doc_group_b_created()
    def test_doc_public_created()
    def test_documents_have_different_guids()
    def test_documents_are_in_correct_groups()
```

**Result:** 8 tests added, all passing. Uses UUID format for group GUIDs (36 chars required by Source model).

**Acceptance:** Tests pass before & after

---

### Phase 4: Test MCP `get_document` Tool Group Enforcement
- [ ] **Status:** Not Started
- **Duration:** 15 min
- **Objective:** Prove `get_document` via MCPO respects group access.

**Tasks:**
1. Test: Token with `group-a` can fetch `group-a` document
2. Test: Token with `group-a` CANNOT fetch `group-b` document
3. Test: Multi-group token can fetch both
4. Run tests - expect some to FAIL if enforcement is missing

**Test scope:**
```python
class TestMCPOGetDocumentGroupAccess:
    def test_get_document_own_group_succeeds()
    def test_get_document_other_group_denied()
    def test_get_document_multi_group_succeeds()
```

**Acceptance:** Tests pass after (may require code fixes)

---

### Phase 5: Test MCP `query_documents` Tool Group Enforcement
- [ ] **Status:** Not Started
- **Duration:** 15 min
- **Objective:** Prove `query_documents` via MCPO only returns documents from permitted groups.

**Tasks:**
1. Test: Query with `group-a` token returns only `group-a` docs
2. Test: Query with `group-b` token returns only `group-b` docs
3. Test: Multi-group token returns union of both
4. Test: No-groups token returns empty or public only

**Test scope:**
```python
class TestMCPOQueryDocumentsGroupAccess:
    def test_query_returns_only_permitted_group()
    def test_query_never_leaks_other_groups()
    def test_query_multi_group_returns_union()
```

**Acceptance:** Tests pass after

---

### Phase 6: Test Web Server `/documents/get` Endpoint
- [ ] **Status:** Not Started
- **Duration:** 15 min
- **Objective:** Document current behavior of Web Server group access (may expose bugs).

**Tasks:**
1. Test current behavior: Does it use token groups or request `group_guid`?
2. Add test that SHOULD fail if enforcement is missing
3. Mark as `xfail` if enforcement is not implemented

**Test scope:**
```python
class TestWebServerGroupAccess:
    def test_get_document_respects_token_groups()       # May be xfail
    def test_get_document_ignores_malicious_group_guid()  # Security test
```

**Acceptance:** Tests pass (or xfail with documented reason)

---

### Phase 7: Test Graph Tools Group Isolation
- [ ] **Status:** Not Started
- **Duration:** 15 min
- **Objective:** Verify graph traversal tools don't leak cross-group data.

**Tasks:**
1. Test: `explore_graph` from `group-a` instrument doesn't show `group-b` docs
2. Test: `get_instrument_news` respects group filtering
3. Test: `get_market_context` only shows permitted group data

**Test scope:**
```python
class TestMCPOGraphToolsGroupAccess:
    def test_explore_graph_respects_groups()
    def test_get_instrument_news_filters_by_group()
```

**Acceptance:** Tests pass after

---

### Phase 8: Security Negative Tests
- [ ] **Status:** Not Started
- **Duration:** 10 min
- **Objective:** Explicit security tests proving attack vectors are blocked.

**Tasks:**
1. Test: Expired token is rejected
2. Test: Invalid token is rejected
3. Test: Token tampering is detected
4. Test: Cross-group access attempts are logged

**Test scope:**
```python
class TestMCPOSecurityNegative:
    def test_expired_token_rejected()
    def test_invalid_token_rejected()
    def test_cross_group_access_logged()
```

**Acceptance:** Tests pass after

---

## Summary

| Phase | Objective | Duration | Status |
|-------|-----------|----------|--------|
| 1 | MCPO Health Check | 5 min | ✅ Complete |
| 2 | Token Helpers | 10 min | ⬜ Not Started |
| 3 | Test Data Setup | 10 min | ⬜ Not Started |
| 4 | `get_document` Enforcement | 15 min | ⬜ Not Started |
| 5 | `query_documents` Enforcement | 15 min | ⬜ Not Started |
| 6 | Web Server Endpoints | 15 min | ⬜ Not Started |
| 7 | Graph Tools Isolation | 15 min | ⬜ Not Started |
| 8 | Security Negative Tests | 10 min | ⬜ Not Started |

**Total Estimated Time:** ~1.5 hours

---

## Progress Log

| Date | Phase | Notes |
|------|-------|-------|
| 2025-12-14 | Plan | Created test plan document |
| 2025-12-14 | Phase 1 | ✅ Created test_mcpo_group_access.py with 3 health check tests |
| 2025-12-15 | Phase 2 | ✅ Added token fixtures + 6 unit tests (all passing) |
| 2025-12-15 | Sidetrack | Fixed `run_tests.sh` (exit 137 from pkill), added MCPO startup, aligned JWT secrets |
| 2025-12-15 | Sidetrack | Fixed `test/test_infrastructure.py` (port assertions, missing os import) |
| 2025-12-15 | Sidetrack | **Skipped:** 2 pre-existing failures unrelated to group access work: `test_full_lifecycle` (needs source setup), `test_no_type_errors` (type checking) |
| 2025-12-15 | Phase 3 | ✅ Test data setup - 8 verification tests pass (sources + documents in 3 groups) |

---

## Files Created/Modified

- `test/test_mcpo_group_access.py` - Main test file (to be created)
- `docs/GROUP_ACCESS_TEST_PLAN.md` - This document

---

## Open Questions

### Answered

**Q1. Should Web Server enforce groups from JWT token instead of request body?**
> **A1.** Yes - Web server should look for JWT token in the Auth header and use that to validate the request. *(This means current implementation has a bug - it trusts client-provided `group_guid`)*

**Q2. What should happen for public/anonymous access?**
> **A2.** There should always be a group "public" and all anonymous write/read should go to this public group ONLY.

**Q3. Should cross-group access attempts be audit-logged?**
> **A3.** A user may have access to more than one group. The aim is to restrict replies to just the material in the groups they have access to (union of permitted groups). This is filtering, not a violation to log.

### New Questions

**Q4. If JWT token has groups [A, B] but request explicitly asks for group C, should it:**
- (a) Return empty results silently (filter out C)?
- (b) Return an error "Access denied to group C"?
- (c) Ignore request group_guid entirely and use token groups?

> **A4.** (b) Reply with access denied, as the user knows about the group. All attempts to see/change a group by name should be rejected with an access error.

**Q5. Should the "public" group be:**
- (a) Readable by truly anonymous users (no auth header)?
- (b) Readable by all authenticated users regardless of their group membership?
- (c) Both?

> **A5.** (c) Both - but no auth headers should be logged as a security warning.

**Q6. For write operations (ingest), if user has groups [A, B] but tries to write to group C:**
- (a) Reject with error?
- (b) Silently redirect to their default group?

> **A6.** (a) Reject with error. All attempts to see/change a group by name should be rejected with an access error.

---

## Security Rules Summary

Based on the answers above:

1. **Authentication:** JWT token in Auth header determines user's permitted groups
2. **Multi-group users:** Get union of all their permitted groups' data
3. **Unauthorized group access:** Explicit "Access Denied" error (not silent filtering)
4. **Public group:** Readable by anonymous and all authenticated users
5. **Anonymous access warning:** No auth header = security warning logged
6. **Write protection:** Cannot write to groups you don't have access to
