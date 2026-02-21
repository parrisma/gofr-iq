# Graph Bootstrap & Validation (Standalone Script)

## Goal
Create a standalone Python script that bootstraps the graph schema, reference data, and validations, and is invoked by simulation scripts. This script must also be suitable for full production deploys to initialize the graph prior to ingestion of real data.

## Background
Simulation currently embeds graph bootstrap logic inside simulation code paths. Production deploys need a consistent, reusable bootstrap step to ensure constraints, indexes, and required reference entities (regions, sectors, event types, factors, etc.) exist before ingestion.

## Non‑Goals
- Changing business logic of ingestion or query services.
- Replacing or removing existing simulation data generation.
- Modifying production start scripts beyond invoking the new bootstrap script when desired.

## Requirements
1. Standalone script runnable from repo root using `uv run`.
2. Performs schema bootstrap:
   - Neo4j constraints (uniqueness for singleton node types).
   - Indexes needed for queries (existing document feed index, etc.).
3. Loads baseline reference graph entities (core taxonomy only):
   - Regions, Sectors, EventTypes, Macro Factors, and their relationships.
   - **NOT** instruments, companies, sources, or clients (those are loaded by simulation or production ingestion).
4. Validates bootstrap completeness with clear, actionable output:
   - Constraint count and names.
   - Existence counts for key node labels.
   - Basic connectivity checks.
5. Idempotent: safe to run multiple times.
6. Usable by simulations and production:
   - Simulation scripts should call it before data ingestion.
   - Production operator can run it independently (no simulation data required).
7. Logging must use project logger (no `print()`), except for CLI banner/summary if needed.

## Proposed Script
- Location: `scripts/bootstrap_graph.py` (new).
- Invoked by simulation scripts (e.g., `simulation/run_avatar_simulation.sh`, `simulation/run_simulation.sh`).
- Optional flags:
  - `--validate-only`: only run validations.
  - `--no-reference-data`: skip taxonomy load (constraints/indexes only).
  - `--verbose`: detailed output.

## Implementation Notes
- Reuse existing logic from:
  - `simulation/setup_neo4j_constraints.py`
  - `simulation/reset_simulation_env.py`
  - `simulation/load_simulation_data.py` (universe builder blocks)
- Create a minimal shared bootstrap module if needed to avoid code duplication.

## Validation Criteria
- Running the script on a fresh graph results in:
  - Constraints created (>=15 expected; exact list logged).
  - Required labels present (Region, Sector, EventType, Factor).
  - No errors on rerun.

## Rollout Plan
1. Add the script and tests (if any).
2. Update simulation scripts to invoke it prior to ingestion.
3. Invoke from `start-prod.sh` after `--reset` or `--nuke` (once services are healthy).
4. Document usage in `docs/readme.md` or `docs/development`.

## Implementation Plan

| # | Task | Test gate |
|---|------|-----------|
| 1 | ✅ **Create `scripts/bootstrap_graph.py`** — 23 constraints, 11 indexes, 30 taxonomy nodes. `--validate-only` / `--no-reference-data` / `--verbose` flags. Idempotent via MERGE. | Tested: fresh, idempotent rerun, validate-only — ALL PASSED. |
| 2 | ✅ **Wire into `start-prod.sh`** — after Neo4j healthy + before app service startup, gated on `--reset` or `--nuke`. | `echo "yes" \| ./docker/start-prod.sh --reset` — bootstrap output in logs, all 5 services healthy. |
| 3 | ✅ **Wire into simulation** — `reset_simulation_env.py` now delegates `init_neo4j_schema()` to `bootstrap_graph.py` via subprocess. Constraint threshold updated to ≥23. `run_avatar_simulation.sh` gets bootstrap via `start-prod.sh --reset`. | Code updated, no standalone test needed (run_avatar_simulation.sh tests end-to-end). |
| 4 | **Run existing tests** — ensure no regressions. | `./scripts/run_tests.sh` passes. |
| 5 | **Post-review** — check for any remaining duplicated schema/taxonomy code. | Clean. |

## Decisions
- **Auto-invoke from start-prod.sh**: Yes — after `--reset` or `--nuke`, once Neo4j is healthy.
- **Reference data scope**: Core taxonomy only (Regions, Sectors, EventTypes, Factors). No instruments, companies, sources, or clients.
