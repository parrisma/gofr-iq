# Test Suite Fix Checklist

## Current Status
- ❌ Unit tests fail due to security lint error
- ❌ Unit tests fail due to ChromaDB connection attempts (3 failures, 5 errors)
- ✅ Integration tests pass (33/33)

---

## Step 1: Fix Bandit Security False Positive
**Priority:** HIGH - Blocks all unit test runs  
**File:** `app/main_mcp.py`  
**Line:** 106

### Issue
Bandit flags `'0.0.0.0'` hardcoded bind address but `# nosec B104` comment is on wrong line (108 instead of 106)

### Fix
- [x] Move `# nosec B104` comment from line 108 to line 106 (the line with the flagged string)
- [x] Verify bandit accepts the suppression
- [ ] Run: `./scripts/run_tests.sh` to verify security check passes

**Expected Result:** `test_code_quality.py::TestCodeQuality::test_security_bandit` passes

---

## Step 2: Skip ChromaDB-Dependent Unit Tests
**Priority:** HIGH - Blocks unit-only test runs  
**Files:** `test/test_mcp_tools.py`, `test/test_integration_hybrid_query.py`

### Issue
Tests that require ChromaDB infrastructure run in unit mode:
- `test_mcp_tools.py::TestMCPServerCreation::test_create_mcp_server` (line ~661)
- `test_mcp_tools.py::TestMCPServerCreation::test_mcp_server_configuration` (line ~678)
- `test_integration_hybrid_query.py::TestHybridQueryIntegration` (5 tests)

These instantiate `EmbeddingIndex` which immediately tries to connect to ChromaDB.

### Fix Options
**Option A:** Add skip decorators (preferred for keeping tests in place)
```python
@pytest.mark.skipif(
    not os.environ.get("GOFR_IQ_CHROMADB_HOST"),
    reason="Requires ChromaDB infrastructure"
)
```

**Option B:** Move to integration-only test files

**Option C:** Mock ChromaDB client in unit tests

### Tasks
- [ ] Review `test_mcp_tools.py` - identify all ChromaDB-dependent tests
- [ ] Review `test_integration_hybrid_query.py` - verify integration markers
- [ ] Apply skip decorators to unit-incompatible tests
- [ ] Verify tests still run in integration mode
- [ ] Run: `./scripts/run_tests.sh` to verify unit tests pass without infrastructure
- [ ] Run: `./scripts/run_tests.sh --mode integration` to verify skipped tests run with infrastructure

**Expected Result:** 
- Unit mode: ~560+ passed, ~190 skipped, 0 failed
- Integration mode: 33 passed (infrastructure tests)

---

## Step 3: Verify Test Categorization
**Priority:** MEDIUM - Ensures proper test isolation

### Review Points
- [ ] Check `pyproject.toml` for pytest markers configuration
- [ ] Verify `@pytest.mark.integration` is properly defined
- [ ] Ensure pytest deselects integration tests in unit mode
- [ ] Document any tests that need reclassification

### Tasks
- [ ] Review pytest configuration in `pyproject.toml`
- [ ] List any miscategorized tests
- [ ] Update markers as needed

---

## Step 4: Run Full Test Suite Validation
**Priority:** FINAL - Verification

### Test Matrix
- [ ] `./scripts/run_tests.sh` (unit mode, no infrastructure)
  - Expected: All unit tests pass, infrastructure tests skipped
  - Duration: < 2 minutes
  
- [ ] `./scripts/run_tests.sh --mode integration` (ephemeral test stack)
  - Expected: Integration tests pass
  - Duration: ~30 seconds
  
- [ ] `./scripts/run_tests.sh --mode all` (full suite with infrastructure)
  - Expected: All tests pass
  - Duration: ~2 minutes
  - Note: Requires valid OpenRouter API key in `.env`

### Success Criteria
- [ ] Zero failures in unit mode
- [ ] Zero failures in integration mode
- [ ] Zero failures in all mode
- [ ] Unit mode runs without starting containers
- [ ] Integration mode properly starts/stops test infrastructure

---

## Step 5: Document and Cleanup
**Priority:** LOW - Housekeeping

- [ ] Update test documentation with proper usage examples
- [ ] Verify all `# nosec` comments have explanations
- [ ] Clean up any debug artifacts
- [ ] Update README if test execution guidance changed

---

## Notes
- Integration tests passed successfully on last run (24 Jan 2026, 13:51)
- Prod stack remains unaffected (external Vault at gofr-vault:8201)
- Test stack uses ephemeral resources (vault-test, offset ports +100)
- OpenRouter key updated in `lib/gofr-common/.env` (sk-or-v1-b05fcb...f5d9)

---

## Quick Commands Reference
```bash
# Fix and verify Step 1
./scripts/run_tests.sh

# Fix and verify Step 2
./scripts/run_tests.sh --mode integration

# Full validation (Step 4)
./scripts/run_tests.sh --mode all

# Stop orphaned test infrastructure
./scripts/run_tests.sh --stop

# Force environment refresh
./scripts/run_tests.sh --refresh-env
```
