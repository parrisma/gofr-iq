# Simulation Parallel Generate + Ingest Spec

## What / Why
Simulation story generation and ingestion are currently largely sequential:
- Generation: one OpenRouter call per story, in a for-loop.
- Ingestion: one `manage_document.sh ingest` subprocess per story, in a for-loop.

This makes `--count` runs slow (wall time scales linearly with story count). The goal is to reduce wall time by running multiple independent story tasks concurrently.

## Scope
In scope:
- Add optional thread-pool based concurrency for:
  - Synthetic story generation (OpenRouter requests).
  - Synthetic story ingestion (document ingest subprocesses).
- Make concurrency configurable via CLI flags (and default to current behavior).
- Keep output format and existing pipeline stages unchanged.

Out of scope:
- Switching to async IO throughout the codebase.
- Changing extraction logic, Neo4j schema, or ingestion semantics.
- Adding new UI/UX beyond flags.

## Requirements
- Default behavior remains sequential unless explicitly enabled.
- Concurrency must be bounded by a max worker count.
- Failures must be isolated per story:
  - One failed story does not crash the whole run.
  - Final summary counts (uploaded/duplicate/failed) still reported.
- Preserve existing timeouts; add no unbounded waits.

## Safety / Constraints
- OpenRouter rate limits: parallelism can increase 429s. Concurrency must be configurable and conservative by default.
- Neo4j / ingestion backend load: parallel ingestion can increase load. Concurrency must be configurable and conservative by default.
- Logging/output must remain readable:
  - Prefer collecting results and printing a stable per-file summary.

## Acceptance Criteria
- A run with `--count N` completes faster when workers > 1 (wall time decreases).
- A run with workers disabled behaves exactly as before.
- `./simulation/run_simulation.sh` continues to work without changes unless new flags are used.
