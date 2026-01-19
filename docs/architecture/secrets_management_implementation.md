# Secrets Management Implementation Guide

**Target State:** Simplified Zero-Trust Architecture
**Date:** 2026-01-19
**Status:** In Progress

## 1. Executive Summary

This document outlines the concrete steps to transition from the current mixed-mode secrets handling to a simplified, centralized, Zero-Trust model. The primary goal is to remove complexity from shell scripts (`start-prod.sh`) and consolidate all Vault logic into Python (`gofr-common` + `scripts/bootstrap.py`).

## 2. Current State Analysis

| Component | Current State | Issues |
| :--- | :--- | :--- |
| `docker/start-prod.sh` | Contains complex inline Python/Bash to check Vault health & unseal. | **Leaky Abstraction**: Redundant logic; hard to maintain; duplicates logic in `bootstrap.py`. |
| `scripts/bootstrap.py` | Handles initialization and basic setup. | **Incomplete Responsibility**: Relies on `start-prod.sh` to ensure Vault is unsealed first. |
| `gofr-common` | Has `AuthService` and new `VaultBootstrap` module. | **Underutilized**: Scripts are not fully leveraging the centralized logic yet. |
| Services (MCP, Web) | Load secrets via AppRole (Good). | **Good foundation**, keep as is. |

## 3. Implementation Plan

### Phase 1: Robustify `gofr-common` (DONE)
*   **Action**: Ensure `VaultBootstrap` class handles all lifecycle states idempotently.
    *   `unseal()`: Should be safe to call if already unsealed.
    *   `initialize()`: Should fail fast or return existing status if already initialized.
    *   `wait_for_ready()`: Internal polling mechanism.

### Phase 2: Empower `scripts/bootstrap.py`
*   **Objective**: Make `bootstrap.py` the *only* command needed to bring Vault from "Container Started" to "Ready for Business".
*   **Changes**:
    *   Add `wait_for_service` logic (don't fail immediately if Vault is just starting).
    *   Integrate `VaultBootstrap` to handle the `Uninitialized -> Initialized -> Unsealed` flow automatically.
    *   Ensure it can read `secrets/` to find unseal keys if Vault is sealed.

### Phase 3: Lobotomize `docker/start-prod.sh`
*   **Objective**: Make the shell script "dumb".
*   **New Flow**:
    1.  `docker compose up -d vault`
    2.  `uv run scripts/bootstrap.py` (This blocks until Vault is ready)
    3.  `uv run scripts/setup_approle.py` (Provisions identities)
    4.  `docker compose up -d ...` (Start services)
*   **Removal**: Delete `ensure_vault_unsealed` function and all inline Python.

### Phase 4: Runtime Contracts
*   **Services**: Continue to expect `/run/secrets/vault_creds`.
*   **Control Scripts**: Update scripts like `manage_document.sh` to use a developer token from `secrets/` or `~/.vault-token` instead of hardcoded logic.

## 4. Operational Procedures

### Bootstrap
```bash
# Clean start
./docker/start-prod.sh --reset
```

### Manual Intervention
If Vault is sealed and automation fails:
```bash
# 1. Check status
export VAULT_ADDR=http://localhost:8201
curl $VAULT_ADDR/v1/sys/health

# 2. Run bootstrap manually (it handles unsealing)
uv run scripts/bootstrap.py
```

### Secret Rotation
```bash
# Rotate service credentials
uv run scripts/setup_approle.py --rotate
```

## 5. Verification Checklist

- [ ] `start-prod.sh` has zero inline Python.
- [ ] `start-prod.sh` has zero default secrets (like `vault_addr=...`).
- [ ] `bootstrap.py` succeeds even if Vault takes 5s to start up (retry logic).
- [ ] `bootstrap.py` succeeds if Vault is already unsealed (idempotency).
- [ ] Services start successfully after bootstrap.
