# Simulation Token Usage Optimization

## Problem Statement

Current simulation uses admin token for all operations including document ingestion. This violates principle of least privilege - document ingestion should use a group-specific token (group-simulation) with minimal necessary permissions.

## Current State

### Token Usage Analysis

**run_simulation.py:**
- Uses `admin_token` for source registration (lines 490-546)
- Uses `admin_token` for source listing (line 806)
- Passes `tokens` dict to `ingest_data()` which includes all group tokens

**ingest_synthetic_stories.py:**
- Resolves token via `get_token_for_group(group)` for each document (line 306)
- Currently uses admin token for source loading (line 365)
- Each synthetic story has `upload_as_group` field (typically "group-simulation")

**gofr_env.py:**
- Provides `get_token_for_group()` which maps:
  - "admin", "group-simulation" → admin_token (line 121-122)
  - "public" → public_token
- Only reads from `secrets/bootstrap_tokens.json`

### Current Token Flow

```
1. run_simulation.py loads admin token
2. Creates group-simulation group in Vault
3. Mints sim-group-simulation token via AuthService
4. Stores in tokens dict
5. ingest_synthetic_stories.py calls get_token_for_group("group-simulation")
6. gofr_env.py returns admin_token (hardcoded mapping)
7. Documents ingested with admin permissions ❌
```

## Desired State

### New Token Strategy

**Principle of Least Privilege:**
- Admin token: ONLY for source/group management operations
- Group-simulation token: For document ingestion operations
- Token persistence: Save group-simulation JWT for later testing/validation

### Token Lifecycle

```
1. run_simulation.py uses admin token to:
   - Create group-simulation group
   - Mint group-simulation token (365 day TTL)
   - Save full JWT to simulation/tokens.json

2. gofr_env.py updated to:
   - Check simulation/tokens.json for group tokens
   - Fallback to admin_token only if no group token exists

3. ingest_synthetic_stories.py:
   - Calls get_token_for_group("group-simulation")
   - Gets actual group token (not admin)
   - Uses for source loading AND document ingestion
```

## Implementation Plan

### Phase 1: Token Persistence (run_simulation.py)

**Changes:**
1. Save minted tokens to `simulation/tokens.json` after `mint_tokens()`
2. Include full JWT strings (not just references)
3. Format:
```json
{
  "group-simulation": "eyJhbGci...",
  "admin": "eyJhbGci..." // bootstrap token for reference
}
```

**Code Location:** Lines 400-410, after mint_tokens() call

### Phase 2: SSOT Module Update (gofr_env.py)

**Changes:**
1. Add `SIMULATION_TOKENS_FILE = WORKSPACE_ROOT / "simulation" / "tokens.json"`
2. Update `get_token_for_group()` logic:
   - Check simulation/tokens.json first for group-* groups
   - Fallback to admin_token only if not found
   - Keep admin/public mappings for backwards compatibility

**Code Location:** Lines 108-130

### Phase 3: Ingestion Update (ingest_synthetic_stories.py)

**Changes:**
1. Use `get_token_for_group("group-simulation")` for source loading (line 365)
2. Verify it returns group token, not admin token
3. No functional changes needed - already calls get_token_for_group()

**Code Location:** Line 365

### Phase 4: Source Operations (run_simulation.py)

**Keep admin token for:**
- `register_mock_sources_via_script()` - Creates sources (lines 490-530)
- `ensure_sources()` - Calls registration (line 537-546)
- Group/token creation (lines 360-405)

**Use group token for:**
- None currently - source registration requires admin permissions

### Phase 5: Testing & Validation

**Test Cases:**
1. Fresh simulation run creates tokens.json with group-simulation token
2. Subsequent runs reuse existing group-simulation token
3. Document ingestion uses group token (verify via logs)
4. Source operations still use admin token
5. Manual testing with saved JWT from tokens.json

## Security Considerations

1. **Token Storage**: simulation/tokens.json contains long-lived JWTs
   - Already in .gitignore (simulation/*.json)
   - 365-day TTL appropriate for dev/testing
   - Production would use shorter TTL + rotation

2. **Permission Boundary**: group-simulation token can only:
   - Ingest documents for group-simulation
   - Query documents accessible to group-simulation
   - Cannot create sources or modify other groups

3. **Admin Token Usage**: Minimized to:
   - Initial group/token setup
   - Source registration (requires admin)
   - Group management operations

## Migration Path

**No Breaking Changes:**
- Existing simulations continue to work
- Bootstrap tokens remain in secrets/bootstrap_tokens.json
- New tokens.json is additive, created on next run

**Backward Compatibility:**
- If simulation/tokens.json doesn't exist, falls back to admin_token
- If group-simulation not in file, falls back to admin_token
- Graceful degradation for older environments

## Success Criteria

1. ✅ simulation/tokens.json created with full group-simulation JWT
2. ✅ gofr_env.get_token_for_group("group-simulation") returns group token
3. ✅ Document ingestion uses group token (not admin)
4. ✅ Source operations still use admin token
5. ✅ Saved JWT can be used for manual testing
6. ✅ No functional regressions in simulation pipeline

## Files to Modify

1. **simulation/run_simulation.py** (Lines 760-770)
   - Save tokens to simulation/tokens.json after minting

2. **lib/gofr-common/src/gofr_common/gofr_env.py** (Lines 48-52, 108-130)
   - Add SIMULATION_TOKENS_FILE constant
   - Update get_token_for_group() to check simulation tokens

3. **simulation/ingest_synthetic_stories.py** (Line 365)
   - Change source loading to use get_token_for_group("group-simulation")
   - Add comment explaining token usage

4. **.github/copilot-instructions.md**
   - Document new token storage location
   - Update "Getting Credentials" section

5. **simulation/README.md**
   - Update tokens.json documentation
   - Explain token persistence strategy
