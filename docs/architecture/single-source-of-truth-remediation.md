# Single Source of Truth Remediation Plan

Goal: Eliminate config/secret duplication; Vault is authoritative for secrets, `gofr_ports.env` is authoritative for ports.

Problems to fix
- Multiple writers to docker/.env (`scripts/bootstrap.py`, `scripts/generate_envs.sh`)
- generate_envs.sh test mode overwrites secrets with fake values
- Bootstrap tokens not persisted in a machine-readable store
- Simulation mints new tokens instead of reusing bootstrap tokens
- JWT secret can diverge between Vault, running services, and docker/.env

Step-by-step plan
1) Freeze docker/.env writes [DONE]
- Stop generate_envs.sh from writing any secrets to docker/.env; allow only port merges. ✅
- Make bootstrap.py the only producer of docker/.env (and only with Vault-derived values). ✅
- Add a guard that refuses to start services if GOFR_JWT_SECRET in docker/.env differs from Vault. ✅

2) Make generate_envs.sh read-only for secrets [DONE]
- In prod mode: validate secrets from Vault but do not write JWT/keys into output files; only emit markers. ✅
- In test mode: write to test-only files (config/generated/secrets.test.env) and never touch docker/.env. ✅
- Add a banner to generated files indicating mode and prohibiting prod use. ✅

3) Persist bootstrap tokens
3) Persist bootstrap tokens [DONE]
- Change bootstrap.py to write tokens into Vault (secret/gofr/config/bootstrap-tokens/tokens) and also to a machine-readable file (config/generated/bootstrap_tokens.json) with 0600 perms. ✅
- Emit a short usage note showing how to source these tokens for CLI/simulation. ✅

4) Make simulation consume bootstrap tokens
4) Make simulation consume bootstrap tokens [DONE]
- Load bootstrap tokens from Vault (secret/gofr/config/bootstrap-tokens/tokens) or config/generated/bootstrap_tokens.json; no silent fallback. ✅
- Default: use bootstrap admin/public, mint only group tokens; add --mint-tokens to mint all tokens explicitly. ✅
- Require explicit VAULT_ADDR/VAULT_TOKEN; fail fast if missing. ✅

5) Enforce JWT_SECRET single source [DONE]
- Simulation entrypoint fetches JWT from Vault and aborts on mismatch with env. ✅
- start-prod.sh blocks startup if docker/.env JWT differs from Vault. ✅
- MCP entrypoint validates GOFR_IQ_JWT_SECRET against Vault and fails fast. ✅
- MCPO auth mode validates GOFR_IQ_JWT_SECRET against Vault and fails fast. ✅
- Web entrypoint validates GOFR_IQ_JWT_SECRET against Vault and fails fast when provided. ✅
- CI pre-commit hook blocks commits containing GOFR_JWT_SECRET in tracked files (excludes generated paths). ✅

6) Align service start scripts to Vault-first [DONE]
- docker/start-prod.sh refuses startup if docker/.env JWT mismatches Vault. ✅
- All entrypoints require explicit Vault context; no stale docker/.env secrets sourced implicitly. ✅
- Dev container usage documented via vault-init sourcing. ✅

7) Documentation and guardrails [DONE]
- Overview updated with single-source-of-truth rules; this plan linked conceptually. ✅
- Pre-commit guard in place; docker/.env generation restricted to bootstrap.py with Vault-derived values. ✅

8) Cleanup and verification [IN PROGRESS]
- Ports files and templates no longer carry secrets/dev tokens; secrets come only from Vault. ✅
- Tracked sample/env files redacted to remove JWT/OpenRouter/Vault secrets (docker/.env, gofriq.env.example, lib/gofr-common/.env/.env.template, gofr_common/config). ✅
- Pending: full end-to-end validation after regenerating docker/.env via bootstrap.py in a clean workspace.

9) Remove silent fallbacks [DONE]
- Eliminate default/fallback values for secrets, tokens, and endpoints; fail fast if not explicitly provided via Vault or required env. ✅
- Add validation helpers that abort startup when any required setting is missing or placeholder (e.g., "change-me"). ✅
- Remove swarm defaults: gofr-swarm.yml now requires JWT/Neo4j/N8N/OpenWebUI secrets without defaults; deploy-swarm.sh fails fast on placeholder/missing secrets and skips placeholder secret creation. ✅
- Add operator helper: scripts/export_vault_for_swarm.sh exports JWT/Neo4j/N8N (and optional OpenAI) from Vault into the shell for swarm deploys. ✅

Owners and sequencing
- Steps 1-2 unblock drift; do these first.
- Steps 3-4 align tokens for simulation; do next.
- Steps 5-6 enforce correctness in runtime scripts.
- Steps 7-8 finalize guardrails and cleanup.
