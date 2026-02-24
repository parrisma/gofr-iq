# Simulation Parallel Generate + Ingest Implementation Plan

1. Identify current hot paths
   - Generation: `simulation/generate_synthetic_stories.py` `SyntheticGenerator.generate_batch`.
   - Ingestion: `simulation/run_simulation.py` `ingest_data` (calls `simulation/ingest_synthetic_stories.py::process_story`).

2. Add bounded thread-pool utilities
   - Use `concurrent.futures.ThreadPoolExecutor`.
   - Provide a small helper to submit tasks and collect results with predictable ordering.

3. Parallelize generation (opt-in)
   - Add an optional `max_workers` argument to `SyntheticGenerator.generate_batch`.
   - Add CLI flag(s): `--gen-workers` (default 1).
   - Worker task:
     - Build scenario + prompt vars.
     - Call OpenRouter.
     - Write output JSON to disk.
   - Handle per-task exceptions; keep retry behavior.

4. Parallelize ingestion (opt-in)
   - Update `simulation/run_simulation.py` `ingest_data` to accept `ingest_workers` (default 1).
   - Add CLI flag: `--ingest-workers` (default 1).
   - Submit `ingest.process_story(...)` for each file and collect results.
   - Print stable summary lines (retain existing OK/duplicate/failed semantics).

5. Guardrails
   - Enforce `workers >= 1`.
   - Consider a low default if enabling by default is later desired (not part of this change).
   - Keep per-task subprocess timeout at 120s (existing).

6. Validation
   - Run a small simulation with sequential and threaded modes and compare:
     - Same number of generated output files.
     - Similar uploaded/duplicate/failed counts.
   - Run `./scripts/run_tests.sh`.
