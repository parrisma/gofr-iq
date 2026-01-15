# Implementation Plan: Production Bootstrap & Test Automation

This tracking document outlines the step-by-step changes required to achieve:
1. **Clean Production Bootstrap:** Ability to start fresh (reset persistent volumes) and bootstrap the entire stack.
2. **Automated Testing:** Full test run for `gofr-common` and `gofr-iq` without manual Vault intervention.

## ✅ COMPLETE - Single Command Production Bootstrap

```bash
# Fresh install:
./docker/start-prod.sh --fresh

# With OpenRouter key:
./docker/start-prod.sh --fresh --openrouter-key sk-or-v1-xxxxx

# Normal restart:
./docker/start-prod.sh

# Nuke & pave:
./docker/start-prod.sh --reset
```

## Tracking Progress

### Phase 1: Test Automation (CI/Dev Container)
- [x] **Step 1:** Implement `scripts/generate_envs.sh` (if missing) in `gofr-common` or ensuring it exists in `gofr-iq` context.
    - _Status:_ **DONE** - Created `/scripts/generate_envs.sh` with `--mode test|prod` support.
    - _Details:_ Test mode uses `GOFR_VAULT_DEV_TOKEN` and generates secrets for ephemeral test env.
- [x] **Step 2:** Update `scripts/run_tests.sh` to use `generate_envs.sh`.
    - _Status:_ **DONE** - Added environment setup section that calls `generate_envs.sh --mode test`.
    - _Details:_ Tests now auto-generate their configuration from defaults.
- [ ] **Step 3:** Setup `gofr-common` test job in CI/Pipeline context.
    - _Goal:_ Ensure `gofr-common` tests pass in isolation.
- [x] **Step 4:** Verify `gofr-iq` integration tests with ephemeral Vault.
    - _Status:_ **DONE** - 787 tests passed.
    - _Details:_ `run_tests.sh` starts `manage-infra.sh --test` and passes.

### Phase 2: Production Bootstrap
- [x] **Step 5:** Create/Refine `docker/reset-prod.sh` (or similar).
    - _Status:_ **DONE** - Created script that cleans volumes and data dirs.
    - _Details:_ Removes all persistent data and credentials for fresh start.
- [x] **Step 6:** Create `scripts/bootstrap.py` for atomic Vault initialization.
    - _Status:_ **DONE** - Implemented complete bootstrap script with auto-init.
    - _Details:_ Handles KV engine setup, JWT secret generation, Auth service init, bootstrap token creation, and docker/.env generation.
    - **Key Features:**
      - `--auto-init`: Automatically initializes fresh Vault
      - Saves credentials to `docker/.vault-init.env`
      - Generates `docker/.env` with all secrets
      - Uses correct `gofr_common.auth` imports
- [x] **Step 7:** Document the "Nuke & Pave" procedure.
    - _Status:_ **DONE** - Created comprehensive production bootstrap guide.
    - _Details:_ Step-by-step walkthrough in docs/getting-started/production-bootstrap.md
- [x] **Step 8:** Create unified `docker/start-prod.sh` script.
    - _Status:_ **DONE** - Single command production startup.
    - _Details:_ Handles port loading, Vault init/unseal, bootstrap, and service startup.
- [x] **Step 9:** Fix `generate_envs.sh --mode prod` to pull from Vault.
    - _Status:_ **DONE** - Now reads JWT secret and API keys from Vault.
    - _Details:_ Uses curl to read secrets, outputs `VAULT_ROOT_TOKEN` correctly.

---

## Files Created/Modified

**New Scripts:**
- `scripts/generate_envs.sh` - Environment generator for test/prod modes
- `scripts/bootstrap.py` - Atomic Vault initialization and token creation
- `docker/reset-prod.sh` - Clean environment reset
- `docker/start-prod.sh` - **NEW** Single-command production startup

**New Documentation:**
- `docs/development/implementation_plan_automation.md` - This tracking document
- `docs/getting-started/production-bootstrap.md` - Complete production bootstrap guide

**Modified:**
- `scripts/run_tests.sh` - Auto-generates test environment
- `docs/architecture/configuration-management.md` - Added test automation section

## Issues Fixed During Implementation

| Issue | Root Cause | Fix |
|-------|------------|-----|
| Wrong imports in bootstrap.py | Had `app.auth.*` | Changed to `gofr_common.auth.*` |
| VaultClient mismatch | Needed VaultConfig wrapper | Added VaultConfig/VaultClient from gofr_common |
| create_token() API wrong | Used dict return/description | Fixed to use string return, no description |
| generate_envs.sh prod stub | Placeholder code | Implemented Vault secret reading via curl |
| Wrong env var name | Compose uses `VAULT_ROOT_TOKEN` | Fixed in both scripts |
| Manual Vault init/unseal | No automation | Added `--auto-init` and auto-unseal |
| Two env files needed | Confusing startup | Created unified `start-prod.sh` |

## Next Actions

1. **CI Pipeline Setup** - Add GitHub Actions workflow
2. **Token Rotation** - Test `--rotate-tokens` functionality
3. **Backup/Restore** - Implement Vault backup procedures
