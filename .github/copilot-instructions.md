# GOFR-IQ Copilot Instructions

## Core Rules
- **Runs in a dev container** and has Docker access.
- **Never use `localhost`**; use service hostnames (e.g., `gofr-neo4j`, `gofr-chromadb`, `gofr-vault`).
- **Always prefer control scripts** to manage services, auth, ingestion, and tests.
- This repo is part of the **GOFR suite** and uses **gofr-common** for shared config/auth/scripts.
- **Keep code simple.**
- **When debugging, check basics first** (env, health, logs, auth, connectivity) to avoid spinning.
- **Run commands so the user can read and help**; avoid hiding output with `head`, `tail`, or heavy filtering.
- **If the user reminds a preferred behavior, suggest updating this file** to make it permanent.
- **For large changes**, follow this workflow:
	1. Write a short **spec document**.
	2. **Peer review** the spec to simplify/refine the design.
	3. Write a **small-step implementation plan** with checkboxes and tests (tests pass before start, pass after finish; update at each step).
	4. **Peer review** the implementation plan to simplify/refine.
	5. Do a **post-review** of code from functional and technical perspectives to ensure it matches the spec and is simple, clean, and robust.

## Start/Stop (use scripts)
```bash
./scripts/start-prod.sh          # Start/restart prod stack
./scripts/start-prod.sh --fresh  # First-time setup
./docker/start-tools-prod.sh     # n8n + OpenWebUI
./scripts/run_tests.sh           # Run tests
```

## Auth (always use gofr-common scripts)
```bash
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
./lib/gofr-common/scripts/auth_manager.sh --docker groups list
./lib/gofr-common/scripts/auth_manager.sh --docker tokens list
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups GROUP --name NAME
```

## Documents (use scripts)
```bash
./scripts/manage_document.sh ingest --source-guid UUID --title "..." --content "..." --token $TOKEN
./scripts/manage_document.sh query --query "search" --token $TOKEN
./scripts/manage_source.sh list
```

## Simulation
```bash
uv run simulation/run_simulation.py --count 50
```

## Logging
- Use the **project logger** (e.g., `StructuredLogger`), **not** `print()` or default logging.
- Logs must be **clear and actionable**, not cryptic.
- All errors must include **cause, references/context**, and **recovery options** where possible.
