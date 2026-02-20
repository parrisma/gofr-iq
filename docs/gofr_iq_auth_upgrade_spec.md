# gofr-iq auth upgrade spec (align to gofr-doc)

Date: 2026-02-19

## Summary

Upgrade gofr-iq authentication/authorization to match the gofr-doc pattern (shared auth across GOFR services): Vault is the source of truth for JWT signing secret, groups, and tokens; services authenticate to Vault via AppRole credentials mounted at `/run/secrets/vault_creds` (VaultIdentity) with auto-renewal; JWT validation uses audience `gofr-api`; Vault auth path prefix is `gofr/auth`; and gofr-iq no longer requires or accepts per-service JWT secrets via env vars (for example `GOFR_IQ_JWT_SECRET`).

This spec defines WHAT and WHY, constraints, and open questions. It intentionally contains no code.

## Goals (what we want)

- Align gofr-iq auth architecture with gofr-doc.
- Remove reliance on JWT secrets provided via environment variables.
- Use VaultIdentity (AppRole creds file at `/run/secrets/vault_creds`) for long-running services.
- Unify JWT validation to audience `gofr-api`.
- Unify Vault storage prefix for groups/tokens to `gofr/auth` to ensure shared auth across services.
- Keep developer/operator workflows consistent by using gofr-common scripts.
- Keep changes minimally invasive where possible (prefer replacing auth initialization blocks over broad refactors).

## Non-goals (what we are not doing)

- Redesigning auth features or permission semantics beyond what is required to align with gofr-doc.
- Introducing new UX, new API surfaces, or new token formats.
- Migrating unrelated infrastructure (Neo4j, Chroma, etc.) except where required for tests or wiring.

## Current state (observed)

Based on the guide:

- gofr-iq expects `GOFR_IQ_JWT_SECRET` (or `GOFR_JWT_SECRET`) and may fail startup when missing.
- gofr-iq compares an env-provided secret to a Vault KV path (startup check).
- AuthService wiring uses a "secret_key" style initialization (via `app/auth/factory.py`).
- Environment variables are a mixed scheme of `GOFR_*` and `GOFR_IQ_*`.
- gofr-iq uses an older gofr-common commit that predates the newer auth patterns (JwtSecretProvider, vault-only stance, newer AppRole provisioning helpers).

## Target state (reference: gofr-doc)

- Vault client is constructed from env via gofr-common factories and prefers VaultIdentity when `/run/secrets/vault_creds` exists.
- JWT secret is obtained at runtime from Vault via a secret provider (JwtSecretProvider).
- Token store and group store are created from env and backed by Vault.
- AuthService is constructed with token/group stores, the secret provider, and audience `gofr-api`.
- Vault auth path prefix used for token/group storage is `gofr/auth`.

## Constraints and requirements

- No `localhost` usage; use Docker service names (Vault: `http://gofr-vault:8201`).
- Python dependency management uses UV only (`uv run`, `uv sync`, `uv add`).
- Do not use `print()` in code; logging must use StructuredLogger.
- Terminal output must not be truncated (no `head`, `tail`, or truncation pipes).
- Tests must be run via `./scripts/run_tests.sh` (not `pytest` directly).
- Do not rewrite pushed git history.
- Services should not require operator Vault tokens at runtime; operator tokens remain for admin tooling only.

## Design decisions to confirm

1. Env var prefix scheme:
   - Option A: Use GOFR_IQ-prefixed auth env vars everywhere.
   - Option B: Keep shared GOFR_* env vars and pass prefix="GOFR" into gofr-common factories.

The guide recommends Option A. If not otherwise specified, we will implement Option A for consistency with gofr-doc.

2. Backends:
   - With newer gofr-common, production auth storage is Vault-only.
   - If gofr-iq tests currently use file/memory backends, tests must be updated to use supported test doubles/utilities.

## Migration and compatibility

- Existing tokens/groups stored under a non-`gofr/auth` prefix may become invisible to upgraded services.
- Services and clients minting JWTs must use `aud=gofr-api`; otherwise verification will fail by design.

## Acceptance criteria

- gofr-iq services start without any JWT secret env vars set.
- gofr-iq reads JWT signing secret from Vault at runtime.
- Token/group storage is under Vault path prefix `gofr/auth`.
- JWT validation enforces audience `gofr-api`.
- Running `./scripts/start-prod.sh` does not require exporting JWT secrets.
- `./scripts/run_tests.sh` passes (or pre-existing unrelated failures are documented and unchanged).

## Risks

- Env prefix mismatch can cause auth to look in the wrong variables and silently misconfigure stores.
- Missing `/run/secrets/vault_creds` in containers can cause fallback auth behavior and break the intended model.
- Tests that assume env-provided secrets or create JWTs without the correct audience will fail and need updates.

## Open questions

- Should gofr-iq align exactly to gofr-doc env var names (Option A), or keep GOFR_* shared vars (Option B)?
- Which gofr-iq services must enforce auth (MCP, MCPO, web), and which can remain auth-neutral?
- Do we need a data migration for existing token/group records stored under any legacy Vault prefixes?

