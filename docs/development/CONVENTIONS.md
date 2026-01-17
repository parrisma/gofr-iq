# Development Conventions

Working agreements for AI-assisted development. Read this before making changes.

## Core Principles

1. **Run existing scripts, don't hand-craft** — If a script exists to generate/create something, use it. Never manually create test data, synthetic documents, or configuration that scripts should produce.

2. **Production config is the source of truth** — The dev container shares the same network and config as production services. Don't manually pass env vars that are already set.

3. **Vault is the single source for secrets** — JWT signing key, bootstrap tokens, and credentials live in Vault. No hardcoded fallbacks.

## Simulation

- **Script**: `uv run simulation/run_simulation.py`
- **Config**: Uses production Vault/JWT automatically (dev container is on `gofr-net`)
- **OpenRouter key**: Stored in `simulation/.env.openrouter`
- **Flags**:
  - `--init-tokens-only` — Create/verify groups, tokens, sources only
  - `--skip-universe --skip-clients` — Skip Neo4j graph loading
  - `--count N` — Generate N synthetic documents

**Never manually create synthetic JSON files.** The generator uses LLM to produce representative test data with proper validation metadata.

## Stack Management

- **Start fresh**: `./docker/start-prod.sh --reset`
- **Vault auto-initializes** on first run; credentials written to `docker/.vault-init.env`
- **Bootstrap runs automatically** after Vault is ready

## Scripts

| Task | Script |
|------|--------|
| List sources | `./scripts/manage_source.sh list --docker` |
| Create source | `./scripts/manage_source.sh create --docker --name "X" --url "Y" --token "$TOKEN"` |
| Ingest document | `./scripts/manage_document.sh ingest --docker ...` |
| Run tests | `./scripts/run_tests.sh` |

## Common Mistakes to Avoid

- ❌ Passing `VAULT_ADDR`, `VAULT_TOKEN`, `GOFR_JWT_SECRET` manually when running from dev container
- ❌ Creating synthetic test documents by hand instead of using the generator
- ❌ Hardcoding API keys or fallback values
- ❌ Using `localhost` for service URLs inside containers (use container names like `gofr-vault`)

## File Locations

| Purpose | Path |
|---------|------|
| Vault init credentials | `docker/.vault-init.env` |
| Docker compose env | `docker/.env` |
| Bootstrap tokens | `config/generated/bootstrap_tokens.json` |
| OpenRouter API key | `simulation/.env.openrouter` |
| Simulation output | `simulation/.env.synthetic` |
| Port configuration | `lib/gofr-common/config/gofr_ports.env` |
