# MCP Server Concurrency Deep Dive: What It Takes to Support 10 Workers

**Date**: 2026-02-22
**Scope**: `gofr-iq` MCP server (`app/main_mcp.py` + `app/mcp_server/mcp_server.py` + services)
**Goal**: Safely handle ~10-way parallel ingest/query load without correctness regressions.

## 1. Current Architecture (What We Actually Run Today)

### 1.1 Server runtime

- Entry point: `app/main_mcp.py`
- App: `FastMCP.streamable_http_app()` (Starlette ASGI app)
- Server: `uvicorn.run(app, host=..., port=..., log_level=...)`
- Observed: no `workers=` passed to uvicorn; therefore single OS process.

### 1.2 Concurrency model today

Even with a single uvicorn worker, the server can handle concurrent requests via asyncio **if** request handlers are non-blocking.

However, in this codebase:

- Tools are `async` at the ASGI layer (FastMCP/Starlette), but **service methods are predominantly synchronous**.
- Many service calls perform network I/O (Neo4j, ChromaDB, OpenRouter) using **blocking** clients.

Net effect:
- You get concurrency primarily from parallel clients (e.g., multiple `curl` / ingestion workers) + interleaving at the server only to the extent the handlers yield.
- Any blocking work inside a request handler will block the event loop and limit true concurrency.

## 2. What “10 worker threads” Actually Means

There are two distinct scaling knobs:

### Option A: 10 OS processes (uvicorn `workers=10`)

- Each worker is a separate Python process.
- Pros: bypasses GIL for CPU-bound work; isolates failures; avoids thread-safety issues (mostly).
- Cons: duplicates in-memory caches/state; multiplies Neo4j/Chroma/HTTP connection pools; more memory.

### Option B: 10 threads inside one process

- Typical approach: run blocking work in a threadpool (`anyio.to_thread.run_sync`, `starlette.concurrency.run_in_threadpool`).
- Pros: one process, one set of caches, fewer total connections.
- Cons: you must make all mutable shared state thread-safe; the GIL limits CPU throughput.

Important: uvicorn itself does not expose a “worker threads” setting the way gunicorn does; uvicorn’s “workers” are **process workers**.

So if the request is literally “10 worker threads”, that’s a design decision inside the app (threadpool usage), not a one-line uvicorn config.

## 3. Thread-Safety / Shared-State Audit (Current Findings)

### 3.1 Module-level singletons (unsafe under threads)

These are unprotected globals; under threads they have init races:

- `app/config.py`: `_config_instance` cached by `get_config()` (no lock)
- `app/services/group_service.py`: `_group_service` cached by `get_group_service()` / `init_group_service()` (no lock)
- `app/services/duplicate_detector.py`: `_default_detector` cached by `get_default_detector()` (no lock)
- `app/services/language_detector.py`: `_default_detector` cached by `get_detector()` (effectively immutable but still init race)

### 3.2 In-process mutable caches (unsafe under threads)

- `DuplicateDetector`:
  - `_hash_index: dict` and `_similarity_index: dict` mutated during ingest.
  - no lock; not safe under multi-thread usage.

- `AliasResolver`:
  - `_cache: OrderedDict` LRU mutated on every lookup; no lock.

- `IngestService`:
  - `_universe_tickers: set[str]` lazy-cached using `hasattr` pattern; no lock.

### 3.3 Lazy connection initialization (unsafe under threads)

These have "check then set" races if multiple threads hit them concurrently:

- `GraphIndex._driver` created lazily in `driver` property.
- `LLMService._client` created lazily in `client` property.
- `LLMEmbeddingFunction._dimensions` computed lazily.

### 3.4 File I/O without locking

- `DocumentStore` and `SourceRegistry` perform filesystem writes without file locks.
- In practice, per-document GUID paths reduce collision risk, but parallel writes to the *same* resource are not guarded.

## 4. External Dependencies Under High Concurrency

### 4.1 Neo4j driver

- Neo4j Python driver is designed to be shared across threads; sessions are created per use.
- Risk is not thread-safety, but connection count: 10 processes = 10 driver pools.

### 4.2 ChromaDB HTTP client

- `EmbeddingIndex` uses ChromaDB HTTP mode.
- Under heavy concurrency, the limiting factor may become Chroma server throughput and network latency.

### 4.3 OpenRouter + httpx

- `LLMService` uses a synchronous `httpx.Client`.
- With high concurrency, you risk:
  - connection pool saturation
  - request queueing
  - long tail latencies and timeouts

## 5. Recommended Path to “10-way Parallel” (Minimal Risk)

### Recommendation: Prefer 10 processes over 10 threads

Because the service layer is sync + mutable, the safest scaling step is **multi-process** (uvicorn workers).

Minimal mechanical change:

- In `app/main_mcp.py`, add `workers=10` to `uvicorn.run(...)`.

But you should treat this as a deploy-time scaling change, not just a code change.

#### Required hardening for multi-process

- Ensure every external dependency has sane connection limits.
- Ensure dedupe logic relies on persistent/shared state (Neo4j `content_hash`, `story_fingerprint`, Chroma similarity), not in-memory state.
- Accept that each worker has its own caches (`AliasResolver`, `DuplicateDetector`, etc.). This is usually OK.

### If you truly need 10 threads in one process

This is a bigger change. You must:

1. Make all shared mutable state thread-safe.
2. Ensure request handlers don’t block the event loop.

Concrete steps:

#### Step 1: Add locks around shared state

- Add a `threading.RLock` to:
  - `DuplicateDetector` to guard `_hash_index` / `_similarity_index`
  - `AliasResolver` to guard `_cache`
  - `IngestService` to guard `_universe_tickers` lazy init

- Add a module-level lock for:
  - `get_config()` singleton initialization
  - `get_group_service()` singleton initialization
  - `get_default_detector()` singleton initialization

#### Step 2: Make lazy init race-free

- Eagerly initialize:
  - `GraphIndex` driver in `__init__` (or guard with a lock)
  - `LLMService` httpx client in `__init__`
  - `LLMEmbeddingFunction.dimensions` in `__init__` if possible

#### Step 3: Stop blocking the event loop

Even if the tool handler is async, if it calls sync functions that do blocking I/O, you don’t get meaningful concurrency.

Two approaches:

- Convert service layer to async clients (preferred long-term)
  - Use `httpx.AsyncClient`
  - Use Neo4j async driver
  - Use async HTTP calls for Chroma

- Or: run sync service calls in a bounded threadpool
  - Wrap tool calls using `run_in_threadpool` for the entire ingest/query path.

#### Step 4: Control concurrency limits

To avoid blowing up dependencies:

- Add a global semaphore for LLM calls (e.g., max 3-5 concurrent OpenRouter requests).
- Add a semaphore for embedding generation.
- Add Neo4j query concurrency limits if needed.

## 6. What I Would Implement (Pragmatic Proposal)

If the near-term goal is “ingest faster” and “don’t melt downstream services”:

1. Add `workers=3` (or 4) first, not 10.
2. Instrument latency per stage (LLM extract, embedding, Neo4j write, Chroma write).
3. Add explicit concurrency limits around LLM/embedding.
4. Only then consider `workers=10`.

Rationale: at `workers=10`, you will likely bottleneck on OpenRouter and/or Chroma, not Python.

## 7. Acceptance Criteria / Tests Before Turning It On

- Run parallel ingest load (10 concurrent clients) and confirm:
  - No data corruption in stored documents.
  - No duplicate explosions (Neo4j `content_hash`/fingerprint works across processes).
  - No elevated 5xx rate from MCP.
  - Neo4j and Chroma remain healthy.

- Run Phase4 bias sweep and confirm metrics still compute deterministically.

## 8. Summary

- If you mean **10 uvicorn workers**: code change is tiny, operational implications are non-trivial.
- If you mean **10 threads inside one process**: code change is moderate-to-large, because several services rely on mutable shared state and unprotected lazy initialization.
- Best tradeoff: multi-process workers + persistent dedupe + bounded concurrency for LLM/embedding.

---

# Implementation Plan: Option A (3 Uvicorn Worker Processes)

Goal: run the MCP server as 3 OS processes to increase throughput without taking on thread-safety refactors.

## Step 0: Decide the control knob

- Use an env var to control worker count at deploy time.
- Name: `GOFR_IQ_MCP_UVICORN_WORKERS`
- Default: `1` (no behavior change unless explicitly enabled)

## Step 1: Implement worker support in the MCP entrypoint

1. Update `uvicorn.run(...)` in `app/main_mcp.py` to accept a `workers` value.
2. Parse `GOFR_IQ_MCP_UVICORN_WORKERS` from env (and optionally allow a CLI flag if you want).
3. Validate: integer >= 1.
4. Log the resolved worker count at startup.

Acceptance check:
- Starting the server with no env var still uses 1 worker.

## Step 2: Wire workers into production compose

1. In `docker/compose.prod.yml`, under the `mcp:` service `environment:`, add:
  - `GOFR_IQ_MCP_UVICORN_WORKERS=${GOFR_IQ_MCP_UVICORN_WORKERS:-3}`

Notes:
- This keeps code default safe, but makes prod opt into 3 workers by default.
- If you prefer explicit control, set the default to 1 and configure `docker/.env` instead.

## Step 3: Verify healthcheck and inter-service wiring still works

1. Start prod: `./docker/start-prod.sh --reset` (or your normal flow).
2. Confirm health endpoint is green:
  - `curl -sf http://localhost:${GOFR_IQ_MCP_PORT}/health`
3. Confirm MCPO still points to MCP correctly (it uses `http://gofr-iq-mcp:${GOFR_IQ_MCP_PORT}/mcp`).

## Step 4: Run repo test gate

- Run: `./scripts/run_tests.sh`

## Step 5: Concurrency smoke test (small)

1. Generate or reuse a small batch (e.g. 20 stories).
2. Ingest with parallel clients: `./simulation/run_simulation.sh --count 20 --skip-generate --ingest-workers 3`
3. Watch MCP logs for 5xx/timeout spikes:
  - `docker logs -f gofr-iq-mcp`

Pass criteria:
- No systematic failures.
- Neo4j and Chroma remain healthy.

## Step 6: Run the Phase 4 flow

1. Ingest the background corpus.
2. Inject calibration stories (Phase3 then Phase4) after background ingest so timestamps are recent.
3. Run:
  - `uv run python simulation/validate_avatar_feeds.py --bias-sweep --lambdas 0,0.25,0.5,0.75,1`
  - `uv run python simulation/measure_bias_sensitivity.py --lambdas 0,0.25,0.5,0.75,1`

## Step 7: Rollback plan

- Set `GOFR_IQ_MCP_UVICORN_WORKERS=1` and restart containers.
- No data migration required.

## Step 8: Operational notes (what to monitor)

- OpenRouter rate limits / timeouts (likely first bottleneck).
- ChromaDB throughput (HTTP server).
- Neo4j connection usage (3 workers => 3 driver pools).
