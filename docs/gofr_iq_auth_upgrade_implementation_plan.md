# gofr-iq auth upgrade implementation plan (align to gofr-doc)

Date: 2026-02-19

Prereq: Spec approved in `docs/gofr_iq_auth_upgrade_spec.md`.

Decisions confirmed:
- Env var scheme: Option A (GOFR_IQ_* everywhere).
- Scope: upgrade all runtimes (MCP + MCPO + web).

Constraints (must follow):
- No `localhost` (Vault is `http://gofr-vault:8201`).
- UV only (`uv run`, `uv sync`, `uv add`).
- No `print()` (use StructuredLogger).
- Tests via `./scripts/run_tests.sh` only.
- Do not truncate terminal output.

## 0. Baseline and safety

0.1 Create a working branch
- `git checkout -b chore/auth-upgrade`

Status: DONE (branch `chore/auth-upgrade` created/checked out).

0.2 Capture baseline tests (record output)
- `./scripts/run_tests.sh`

Status: DONE (exit code 1).
Observed failure (understood, not auth-upgrade-specific): missing `GOFR_IQ_OPENROUTER_API_KEY`.
Baseline log: `logs/auth_upgrade_baseline_2026-02-19.txt`
ASCII-only baseline log (preferred): `logs/auth_upgrade_baseline_2026-02-19_nocolor.txt`

Stop condition:
- If baseline is red for unrelated reasons, record failures and proceed only if they are understood and not in the auth upgrade path.

## 1. Align gofr-common to the gofr-doc version

Goal: upgrade `lib/gofr-common` to match gofr-doc so `JwtSecretProvider` and the current VaultIdentity/AppRole pattern is available.

1.1 Identify the gofr-common commit used by gofr-doc
- From `/home/gofr/devroot/gofr-doc/lib/gofr-common`, record `git rev-parse HEAD`.

1.2 Update gofr-iq gofr-common to that commit
- `cd lib/gofr-common`
- `git fetch --all --tags`
- `git checkout <commit_from_gofr_doc>`
- `cd ../..`

Note (executed in this dev container): `lib/gofr-common` `origin` was switched from SSH to HTTPS (`https://github.com/parrisma/gofr-common.git`) to avoid SSH key/known_hosts failures.

1.3 Sync dependencies
- `uv sync`

Status: DONE.
gofr-common pinned to gofr-doc commit: `1fc6afd6a077cc7d1bd9a8d48e7d74ced21f6793`.
uv sync log: `logs/auth_upgrade_uv_sync_2026-02-19.txt`

1.4 Sanity check imports
- Run a small targeted test subset if available, otherwise proceed.

Status: DONE.
Post-upgrade fix: added PyJWT (`uv add pyjwt`) to resolve `ModuleNotFoundError: No module named 'jwt'` during MCP startup.
uv add log: `logs/auth_upgrade_uv_add_pyjwt_2026-02-19.txt`
Runner pre-flight: `./scripts/run_tests.sh --check` exit 0.
Check log: `logs/auth_upgrade_post_step1_check_2026-02-19.txt`

Stop condition:
- If `uv sync` fails due to dependency conflicts, resolve before continuing (do not implement auth changes on a broken dependency graph).

## 2. Standardize env vars to GOFR_IQ_* (Option A)

Goal: one consistent prefix for all auth-related gofr-common factories in gofr-iq.

2.1 Update env templates and scripts to export:
- `GOFR_IQ_AUTH_BACKEND=vault`
- `GOFR_IQ_VAULT_URL=http://gofr-vault:8201`
- `GOFR_IQ_VAULT_MOUNT_POINT=secret`
- `GOFR_IQ_VAULT_PATH_PREFIX=gofr/auth`

Files to review/update (as applicable):
- `scripts/gofriq.env` and/or `scripts/gofriq.env.example`
- any docker env generation scripts used by `./scripts/start-prod.sh`

2.2 Remove or de-emphasize per-service JWT secret vars in docs/help
- Remove references that imply `GOFR_IQ_JWT_SECRET` is required.

Verification:
- Grep for `GOFR_IQ_JWT_SECRET` and `GOFR_JWT_SECRET` usage locations; keep only operator tooling needs (if any) and remove service runtime requirements.

Status: DONE.
Updated env/templates/scripts/docs to prefer GOFR_IQ_* auth/Vault variables:
- `scripts/gofriq.env`, `scripts/gofriq.env.example`
- `scripts/test_env.sh`, `scripts/dump_environment.sh`, `scripts/run_mcp.sh`
- `scripts/start-prod.sh` (ensures GOFR_IQ_* Vault/auth config is written to `docker/.env`)
- `docker/.env.example`
- `docs/development/configuration.md`, `docs/architecture/overview.md`, `docs/reference/project-summary.md`, `docs/architecture/authentication.md`

## 3. Add AppRole provisioning config and helper script

Goal: provision AppRole creds like gofr-doc, using gofr-common tooling, and generate creds that can be mounted into containers at `/run/secrets/vault_creds`.

3.1 Create `config/gofr_approles.json`
- Mirror gofr-doc format.
- Include at minimum role: `gofr-iq`.
- Include optional operator role: `gofr-admin-control` (recommended if gofr-doc uses it).

Note (core secrets):
- The JWT signing secret and the LLM API key are both core secrets under `secret/data/gofr/config/*`.
- The same AppRole/policies used for JWT secret reads should be used for the LLM API key as well (no GOFR-IQ specific AppRole is required).

3.2 Add `scripts/ensure_approle.sh`
- Preconditions:
  - Vault is running/unsealed.
  - Root token is available at `secrets/vault_root_token`.
- Behavior:
  - Run `uv run lib/gofr-common/scripts/setup_approle.py --project-root ... --config config/gofr_approles.json`.
  - Ensure generated creds land in `secrets/service_creds/` in the expected gofr-common layout.

3.3 Validate creds existence
- Confirm `secrets/service_creds/...` files exist for the roles.

Stop condition:
- If policies/paths differ from gofr-doc after the gofr-common upgrade, align to gofr-doc before moving on.

Status: DONE (files added; provisioning can be run when Vault artifacts are present).
Added:
- `config/gofr_approles.json`
- `scripts/ensure_approle.sh`

Note:
- `secrets/` is a symlink to `lib/gofr-common/secrets` in this repo, so tooling may log resolved credential paths under `lib/gofr-common/secrets/service_creds` even though the stable mount path is `secrets/service_creds`.

## 4. Wire VaultIdentity creds into Docker services

Goal: all long-running services (MCP, MCPO, web) use VaultIdentity by reading `/run/secrets/vault_creds`.

4.1 Dev / local compose wiring
- Identify which compose files are used by dev/test/prod (for example `docker/docker-compose.yml`, `docker/docker-compose-test.yml`).
- For each service container that needs auth:
  - Mount the correct creds file to `/run/secrets/vault_creds`.
  - Ensure GOFR_IQ_* Vault env vars are present.

4.2 Prod wiring
- Ensure `./scripts/start-prod.sh` results in containers with `/run/secrets/vault_creds` present.

Verification:
- In each running container: `test -f /run/secrets/vault_creds`.

Stop condition:
- If `/run/secrets/vault_creds` is missing in prod containers, treat as misconfiguration and fix before code-level auth refactors.

Status: DONE (prod wiring).
Updated:
- `docker/docker-compose.yml` mounts `/run/secrets/vault_creds:ro` for `mcp`, `mcpo`, `web` from `secrets/service_creds/`.
- `scripts/start-prod.sh` now provisions AppRole creds via `scripts/ensure_approle.sh`.

Note: `docker/docker-compose-test.yml` intentionally remains dev-token based (no VaultIdentity mount) to avoid requiring AppRoles in the ephemeral test Vault.

## 5. Replace JWT env secret usage with JwtSecretProvider (code changes)

Goal: remove `GOFR_IQ_JWT_SECRET` requirements and runtime comparisons; read secret from Vault via provider; use Vault-backed token/group stores.

5.1 Identify all auth initialization entrypoints
- MCP: `app/main_mcp.py`
- MCPO: `app/main_mcpo.py` (or equivalent)
- Web: `app/main_web.py`
- Auth factory: `app/auth/factory.py`

5.2 Update auth initialization in each runtime
- Remove any requirement for `GOFR_IQ_JWT_SECRET` / `GOFR_JWT_SECRET` as service runtime inputs.
- Remove any "env secret must equal Vault secret" startup checks.
- Create a Vault client using gofr-common factory with env prefix `GOFR_IQ`.
- Create `JwtSecretProvider` with Vault path `gofr/config/jwt-signing-secret`.
- Create token/group stores using gofr-common store factory and the same Vault client.
- Construct AuthService with:
  - token store + group registry/store
  - secret provider
  - audience `gofr-api`
  - env_prefix consistent with GOFR_IQ

5.3 Update `app/auth/factory.py` public interface
- Replace any `secret_key` parameter with `secret_provider`.
- Ensure the factory accepts `audience` with default `gofr-api`.

5.4 Error handling and logging
- Any auth init failures must surface:
  - cause
  - context (paths/prefix, vault url, which runtime)
  - recovery options
- Use StructuredLogger (no prints).

Verification:
- Service startup works without JWT secret env vars.
- Auth rejects JWTs missing/incorrect audience.

Status: DONE.
Updated code to remove JWT-secret-by-env and Vault compare checks, and to wire auth via Vault-backed JwtSecretProvider + stores:
- `app/auth/__init__.py`
- `app/auth/factory.py`
- `app/main_mcp.py`
- `app/main_mcpo.py`
- `app/main_web.py`

Updated runtime wiring to stop passing JWT secrets into services:
- `docker/docker-compose.yml`
- `docker/docker-compose-test.yml`
- `docker/entrypoint-prod.sh`

Sanity check:
- `./scripts/run_tests.sh --check` exit 0 (log: `logs/auth_upgrade_post_step5_check_2026-02-19.txt`)

## 6. Enforce Vault auth path prefix `gofr/auth`

Goal: ensure token/group registry locations are shared across GOFR services.

6.1 Confirm env var values
- `GOFR_IQ_VAULT_PATH_PREFIX=gofr/auth`

6.2 Validate reads/writes
- Using admin tooling (auth_manager), confirm groups/tokens appear under the shared prefix.

Stop condition:
- If gofr-iq writes tokens/groups elsewhere, fix prefix wiring before updating tests.

Status: DONE.
Validation performed (prod Vault on Docker network; no JWT secret env vars involved):
- Started Vault: `./docker/manage-infra.sh vault`
  - Note: `docker/manage-infra.sh` was fixed to call `lib/gofr-common/scripts/manage_vault.sh start` (previously invoked without a subcommand and exited with usage).
- Provisioned/verified AppRole creds: `./scripts/ensure_approle.sh`
- Admin validation (Docker mode):
  - `source <(./lib/gofr-common/scripts/auth_env.sh --docker)`
  - `./lib/gofr-common/scripts/auth_manager.sh --docker groups list`
  - Direct Vault KV inspection:
    - `vault kv list secret/gofr/auth/groups`
    - `vault kv list secret/gofr/auth/tokens`
Observed:
- Groups and tokens exist under `secret/gofr/auth/*` (shared prefix is active).

## 7. Update operator/dev scripts and docs

Goal: make scripts reflect the new operational model.

7.1 Update scripts to remove JWT secret requirements
- `scripts/run_mcp.sh`, `scripts/run_mcpo.sh`, `scripts/run_web.sh` (and any related help text).
- Replace with:
  - "Vault must be available"
  - "AppRole creds must be present/mounted"
  - optionally, "run `./scripts/ensure_approle.sh`"

7.2 Keep operator tooling guidance
- `source <(./lib/gofr-common/scripts/auth_env.sh --docker)` for admin commands.
- `./lib/gofr-common/scripts/auth_manager.sh --docker ...` for groups/tokens.

Verification:
- Running scripts does not instruct users to export JWT secrets.

Status: DONE.
Updates applied:
- `scripts/run_mcp.sh`: removed legacy JWT-secret-by-env note; updated operator tooling guidance to `source <(./lib/gofr-common/scripts/auth_env.sh --docker)`; aligned prod script reference to `scripts/start-prod.sh`.
- `scripts/run_mcpo.sh`: removed `localhost` default; defaults MCP host to `gofr-iq-mcp` (Docker service/container name) and removed `localhost` URL output.
- `scripts/run_web.sh`: updated operator tooling guidance to the process-substitution form.
- `scripts/manage_servers.sh`: removed unused `GOFR_IQ_JWT_SECRET` placeholder export.
- `scripts/start-prod.sh`: no longer exports/writes `GOFR_IQ_JWT_SECRET` to `docker/.env`; only verifies `secret/gofr/config/jwt-signing-secret` exists in Vault; removed `localhost` URLs from the final service summary.
- `docs/development/conventions.md`: removed `GOFR_JWT_SECRET` from docker/.env SSOT references.

## 8. Update tests

Goal: tests stop depending on per-service JWT secrets and validate the new expected behavior.

8.1 Inventory affected tests
- Find tests setting `GOFR_IQ_JWT_SECRET` / `GOFR_JWT_SECRET`.
- Find tests minting raw JWTs and ensure `aud=gofr-api`.

8.2 Choose the correct approach per test
- If auth is not under test: use `--no-auth` / disable auth via existing toggles.
- If auth is under test: prefer Vault-backed integration tests (token/group stores, secret provider).
- If fully offline tests are required: use gofr-common testing helpers (if provided by the upgraded gofr-common), or introduce application-level test doubles.

8.3 Run targeted tests
- `./scripts/run_tests.sh -k auth -v` (or closest matching keywords).

8.4 Run full suite
- `./scripts/run_tests.sh`

Stop condition:
- Do not skip failing tests; fix underlying issues.

Status: DONE.
Full suite result:
- `./scripts/run_tests.sh` passed: 893 passed, 1 skipped (aikido-local-scanner not installed).
Notes:
- `GOFR_IQ_OPENROUTER_API_KEY` was sourced from Vault for the test process only (exported in-shell) to avoid the known baseline failure when the key is missing.

## 9. Add a bootstrap script (post-upgrade)

Goal: one idempotent command to bring up prerequisites, matching gofr-doc operator workflow.

9.1 Add `scripts/bootstrap_gofr_iq.sh` only after Steps 1-8 are green
- Responsibilities (match gofr-doc as closely as practical):
  - ensure submodules present
  - ensure Vault running/unsealed
  - provision/sync AppRole creds via gofr-common `setup_approle.py`
  - optionally start stacks
  - optionally run `./scripts/run_tests.sh`

## 10. Verification checklist (acceptance)

- Code/build sanity checks (if present).
- Targeted auth tests pass.
- Full test suite passes: `./scripts/run_tests.sh`.
- Dev run:
  - Vault running/unsealed
  - `./scripts/ensure_approle.sh` succeeds
  - MCP, MCPO, web start without JWT secret env vars
- Prod run:
  - `./scripts/start-prod.sh` works without exporting JWT secrets

Known pitfalls to watch:
- Env prefix mismatch (GOFR_IQ_* set, but factory called with prefix GOFR).
- Missing `/run/secrets/vault_creds` in containers (VaultIdentity not active).
- Vault path prefix not `gofr/auth` (auth island).
- JWT audience mismatch (`aud` must be `gofr-api`).

## 11. Move LLM API key to Vault (core secret) + dev/test injection

Goal: stop passing the LLM API key (OpenRouter) via env vars in prod. Read it from Vault by default using the same runtime pattern as `JwtSecretProvider`. For dev/test, keep the real key in a gitignored file and inject it into the ephemeral test Vault for each test cycle.

Background (current state):
- Vault already contains `secret/gofr/config/api-keys/openrouter` with data key `value`.
- Code currently reads `GOFR_IQ_OPENROUTER_API_KEY` from the environment (MCP startup hard-fails if missing).
- `scripts/start-prod.sh` currently pulls the key from Vault and exports it as an env var before starting services.

Design constraints:
- This is a core/shared secret path (no GOFR-IQ specific path). Use `gofr/config/api-keys/openrouter`.
- Follow the existing provider pattern (VaultClient + TTL cache + thread safety). No ad-hoc Vault reads sprinkled across services.
- Backwards compatibility: keep env var override working during the transition (env var wins if set; otherwise use Vault).

11.1 Confirm Vault policy access for AppRoles
- Confirm the service policy used by MCP (`gofr-mcp-policy`) can read `secret/data/gofr/config/*`.
- If policy coverage is missing in your environment, add it to gofr-common policy definitions.

Note:
- This should be the same AppRole/policy access model as the JWT signing secret (`gofr/config/jwt-signing-secret`).

Stop condition:
- If MCP AppRole cannot read `secret/data/gofr/config/api-keys/openrouter`, fix policy before touching application logic.

11.2 Implement a Vault-backed OpenRouter key provider in gofr-common
- Add `OpenRouterKeyProvider` in gofr-common:
  - inputs: `vault_client`, `vault_path` (default: `gofr/config/api-keys/openrouter`), `cache_ttl_seconds`
  - behavior: `get()` reads KV v2 secret dict and returns `value` with TTL caching
  - logging: do not log the key; log only fingerprint/metadata (match `JwtSecretProvider` style)
- Keep `JwtSecretProvider` unchanged.

Verification:
- Unit-test the provider behavior (cache hit/miss, missing key raises) in gofr-common if tests exist there.

11.3 Wire provider into gofr-iq runtime config / auth factory
- In gofr-iq, create an LLM API key provider using:
  - Vault path: `gofr/config/api-keys/openrouter`
  - TTL cache: 300s (same as JWT secret provider unless you have a reason to differ)
- Make it accessible to code that builds LLM clients (prefer passing provider down; avoid global env reads).

Backwards compatibility rule:
- If `GOFR_IQ_OPENROUTER_API_KEY` is set, use it.
- Else, read from Vault via provider.

11.4 Remove env-var hard dependency in server startup and LLM service
- MCP server startup must no longer read `GOFR_IQ_OPENROUTER_API_KEY` directly or hard-fail on missing env var.
- LLM service must prefer provider (or config-provided key) and only fall back to env var as the override.
- Error paths must be explicit and actionable (missing Vault access vs missing secret vs misconfig).

Verification:
- With Vault running and AppRole creds mounted, start MCP without setting `GOFR_IQ_OPENROUTER_API_KEY` and confirm LLM is available.
- With env var set to a known different value, confirm env override wins.

11.5 Update prod/dev scripts to stop exporting the key
- Update `scripts/start-prod.sh`:
  - remove the logic that pulls OpenRouter key from Vault and exports `GOFR_IQ_OPENROUTER_API_KEY`
  - keep Vault readiness checks (Vault must be up; AppRole creds must exist)
- Update compose/service env wiring to stop passing `GOFR_IQ_OPENROUTER_API_KEY` into containers.

Stop condition:
- If any service still requires the env var at startup, do not remove it from scripts/compose yet; fix the code first.

11.6 Dev/test: store real key in a gitignored file and inject into ephemeral test Vault each cycle
- Add a local-only file (gitignored by existing rules): `secrets/llm_api_key`.
  - contents: a single line containing the OpenRouter API key
  - do not commit it
- Update `scripts/run_tests.sh`:
  - if `GOFR_IQ_OPENROUTER_API_KEY` is set, treat it as an override (optional)
  - else read the key from `secrets/llm_api_key`
  - write it into the ephemeral test Vault at `secret/data/gofr/config/api-keys/openrouter` with data `{ "value": "..." }`
  - remove the current hard-fail that requires `GOFR_IQ_OPENROUTER_API_KEY` to be set in the test process env

Verification:
- Run `./scripts/run_tests.sh` with no `GOFR_IQ_OPENROUTER_API_KEY` exported and confirm the suite still passes.

11.7 Acceptance criteria
- Prod: services start and can use LLM without `GOFR_IQ_OPENROUTER_API_KEY` being passed via env vars.
- Dev/test: `./scripts/run_tests.sh` injects the key into ephemeral Vault each run from `secrets/llm_api_key`.
- Security: no plaintext OpenRouter API key is printed in logs or written to committed files.

Status: DONE.
Updates applied:
- gofr-common: added `OpenRouterKeyProvider` (Vault KV v2, TTL cached) and exported it from `gofr_common.auth`.
- gofr-iq MCP startup: removed hard dependency on `GOFR_IQ_OPENROUTER_API_KEY`; reads from Vault by default (env var override supported).
- gofr-iq LLM service: supports Vault provider fallback and improved configuration error messaging.
- `scripts/run_tests.sh`: no longer hard-fails when `GOFR_IQ_OPENROUTER_API_KEY` is unset; injects OpenRouter key into ephemeral test Vault from `secrets/llm_api_key` when available.
- Prod wiring: removed `GOFR_IQ_OPENROUTER_API_KEY` export/write from `scripts/start-prod.sh` and removed it from `docker/docker-compose.yml`.

Verification:
- `./scripts/run_tests.sh` passed: 893 passed, 1 skipped.
