# run_tests.sh Refactor Plan

Incremental plan to simplify and harden the test runner without breaking existing workflows. Each step should land as its own PR/checkpoint.

## 1. Baseline Guardrails

- [x] Add `trap cleanup_environment EXIT INT TERM` near the top of `scripts/run_tests.sh`.
- [x] Update `cleanup_environment` to tolerate unset `GOFR_IQ_TOKEN_STORE` and document its responsibilities.
- [x] Remove the unused `start_chromadb`, `start_vault`, and `start_neo4j` helpers (they are no longer invoked).

## 2. Externalize Infrastructure Control

- [x] Create `scripts/test_env.sh` (or similar) with commands `start`, `stop`, and `status` that wrap `docker/manage-infra.sh`/`docker compose`.
- [x] Replace inline infrastructure lifecycle logic in `run_tests.sh` with calls to the new helper.
- [x] Verify the helper is reusable from CI and local shells.

## 3. Streamline Server Startup

- [x] Move MCP/Web/MCPO processes into the Docker test compose file (or a `uvicorn` helper script).
- [x] Update `run_tests.sh` to rely on compose health checks instead of bespoke `nohup` + `curl` loops.
- [x] Drop `start_mcp_server`, `start_web_server`, `start_mcpo_server`, and the `free_port`/`port_in_use` helpers once compose controls the lifecycle.

## 4. Light-Weight Unit Mode

- [x] Add a `--mode {unit,integration,all}` flag (default `unit`).
- [x] For `unit`, skip environment generation, infrastructure start, and heavy cleanup; simply run `pytest -m 'not integration'` (or similar marker-based filter).
- [x] Update docs/README sections that describe running tests to reflect the new flag.

## 5. Marker-Driven Pytest Profiles

- [x] Define `integration` (and optional `e2e`) markers in `pytest.ini` (via `pyproject.toml`).
- [x] Replace the current `-k "not integration"` filtering with marker expressions based on `--mode`.
- [x] Ensure CI pipelines pass `--mode integration` (or `all`) explicitly. *(No CI workflows present in repo today; documented that there's nothing to update yet.)*

## 6. Optional Environment Refresh

- [x] Add `--refresh-env` to trigger `purge_local_data.sh` and `generate_envs.sh`.
- [x] Default to reusing existing `.env` material for faster inner-loop runs.
- [x] Document when/why to use the refresh flag (new developer onboarding, CI, etc.).

## 7. Final Cleanup and Docs

- [x] Collapse redundant CLI flags (`--all`, `--with-servers`, `--integration`, etc.) into the single `--mode` concept plus `--coverage`/`--docker`.
- [x] Update `readme.md` and `docs/development.md` testing sections with the new workflow.
- [x] Remove leftover references to deleted helpers (in code/docs) and verify `shellcheck` passes on the simplified script.
