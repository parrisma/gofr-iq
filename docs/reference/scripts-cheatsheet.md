# Management Scripts Cheat Sheet

## Token Access (quick)

- Operator tasks (list/create tokens):
	```bash
	source <(./lib/gofr-common/scripts/auth_env.sh --docker)
	./lib/gofr-common/scripts/auth_manager.sh --docker tokens list
	./lib/gofr-common/scripts/auth_manager.sh --docker tokens inspect --name bootstrap-admin
	```
	Exports VAULT_ADDR, 1h VAULT_TOKEN, GOFR_JWT_SECRET. Does **not** export bootstrap JWTs.

- App tasks (docs ingest/query):
	```bash
	ADMIN_TOKEN=$(python3 -c "import json; print(json.load(open('secrets/bootstrap_tokens.json'))['admin_token'])")
	./scripts/manage_document.sh query --query "market" --n-results 10 --token "$ADMIN_TOKEN"
	```
	`secrets/bootstrap_tokens.json` holds 365-day `admin_token` and `public_token` strings.

---

## Quick Reference

| Script | Location | Purpose | Usage |
|--------|----------|---------|-------|
| **start-prod.sh** | `docker/` | Start full production stack | `./docker/start-prod.sh [--fresh\|--reset] [--openrouter-key KEY]` |
| **run-dev.sh** | `docker/` | Start dev infrastructure only | `./docker/run-dev.sh` |
| **run_simulation.sh** | `simulation/` | Generate test data & ingest | `./simulation/run_simulation.sh --count 5 [--regenerate]` |
| **auth_env.sh** | `lib/gofr-common/scripts/` | Mint operator token (Vault) | `source <(./lib/gofr-common/scripts/auth_env.sh --docker)` |
| **auth_manager.sh** | `lib/gofr-common/scripts/` | Manage groups/tokens | `./lib/gofr-common/scripts/auth_manager.sh --docker groups list` |
| **bootstrap.py** | `scripts/` | Initialize Vault & secrets | `uv run scripts/bootstrap.py --auto-init [--openrouter-key KEY]` |
| **setup_approle.py** | `scripts/` | Provision service identities | `uv run scripts/setup_approle.py` |
| **manage_document.sh** | `scripts/` | Ingest/query/delete docs | `ADMIN_TOKEN=$(python3 -c "...") && ./scripts/manage_document.sh query --token "$ADMIN_TOKEN"` |
| **manage_source.sh** | `scripts/` | List/create sources | `./scripts/manage_source.sh list\|create` |
| **manage_servers.sh** | `scripts/` | Health check services | `./scripts/manage_servers.sh health` |
| **run_tests.sh** | `scripts/` | Execute pytest suite | `./scripts/run_tests.sh [--refresh-env]` |
| **generate_envs.sh** | `scripts/` | Generate port config (SSOT) | `./scripts/generate_envs.sh` |
| **build-prod.sh** | `docker/` | Build production image | `./docker/build-prod.sh` |
| **purge_local_data.sh** | `scripts/` | Clear local data dirs | `./scripts/purge_local_data.sh` |
| **reset_simulation_env.sh** | `simulation/` | Clear simulation data | `./simulation/reset_simulation_env.sh` |

**See full docs:** [management-scripts.md](management-scripts.md)
