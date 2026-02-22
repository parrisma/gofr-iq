# GOFR-IQ Ingestion Optimization Proposal (Systems + Prompt)

Date: 2026-02-22
Owner: Systems Engineering / Prompt SME review
Scope: Document ingestion path (MCP tool -> IngestService -> file store + ChromaDB + Neo4j + LLM extraction)

## 0. Executive Summary

The current ingestion path is functionally correct but throughput is dominated by synchronous, per-document network calls (OpenRouter for extraction and embeddings; ChromaDB upserts; Neo4j writes) performed inline in the request path. The highest-leverage optimizations are:

1. Reorder ingest stages to avoid expensive LLM work for obvious duplicates.
2. Reduce prompt tokens and constrain extraction to cheaper, more deterministic outputs.
3. Add batching and session reuse in the ingestion client (simulation and future production feeders).
4. Decouple ingestion acknowledgement from extraction/graph writes (optional, if "fast ingest" is a product requirement).
5. Add explicit concurrency limits and backpressure to avoid melting OpenRouter/Chroma/Neo4j under parallel workers.

This doc proposes incremental changes that can be adopted independently, with clear acceptance criteria.

## 1. Current Ingestion Process (What Runs Today)

### 1.1 Primary runtime path (MCP server)

Entry point:
- Tool: `ingest_document` in `app/tools/ingest_tools.py`
- Service: `IngestService.ingest()` in `app/services/ingest_service.py`

High-level stages (as implemented):
1. Generate a new UUID doc GUID.
2. Validate source (fallback: metadata "meta_source_name" -> lookup-by-name).
3. Validate word count.
4. Detect language.
5. LLM extraction (required when graph index enabled).
6. Duplicate detection (hash, optional fingerprint, embedding similarity).
7. Save canonical document to file store.
8. Embed document into ChromaDB (chunking + upsert).
9. Write document + relationships into Neo4j.
10. Register doc in in-memory duplicate detector.
11. If any failure during steps 5-10: rollback file + embedding + graph.

Notes:
- The service is synchronous and runs in the request path.
- The LLM extraction prompt is large (`GRAPH_EXTRACTION_SYSTEM_PROMPT`).
- Duplicate detection supports a cheap hash check, but ingestion currently performs extraction before calling `DuplicateDetector.check()`.

### 1.2 Simulation ingestion path

The simulation harness ingests JSON stories via:
- `simulation/ingest_synthetic_stories.py` calling `./scripts/manage_document.sh ingest` via subprocess for each story.

Operational costs:
- One process spawn per document.
- One MCP initialize + tool call round-trip per document.
- No metadata is currently passed through for ingestion (commented TODO).

### 1.3 Concurrency and shared-state constraints

The repo already documents known concurrency constraints and shared mutable state in:
- `docs/mcp_concurrency_10_workers.md`

Key takeaways:
- Many dependencies are blocking (Neo4j, ChromaDB, OpenRouter via sync httpx).
- There are unprotected mutable caches and lazy initialization patterns.

## 2. Primary Bottlenecks (Time and Cost)

In rough order of impact:

1. LLM extraction in the critical path
   - Adds external latency + cost per document.
   - Current system prompt is long; repeated instructions increase tokens and variance.
   - Max tokens is currently set to 1000, which increases tail latency under contention.

2. Embedding generation and ChromaDB upserts
   - Chunking expands a single doc into many embedding calls.
   - Duplicate detection may also call embeddings for the query (semantic similarity), which is expensive.

3. Neo4j writes per document
   - Document node creation plus multiple relationship creations can cause many Cypher operations.
   - Per-document sessions/transactions increase overhead.

4. Client-side orchestration overhead (simulation and potential feeders)
   - Per-document subprocess + per-document MCP session initialization is high overhead.

5. Rollback strategy is "best effort" and can create long tail
   - If one downstream dependency is slow/unavailable, request time increases.
   - Rollback failures are logged but can still leave partial state depending on failure point.

## 3. Proposed Optimizations (Prioritized)

### 3.1 Quick wins (1-3 days, low risk)

A. Avoid LLM extraction for exact duplicates
- Today, the ingest path always runs extraction before duplicate checking.
- Change to a two-stage duplicate check:
  1) Hash check first (no LLM, no embeddings).
  2) Only if not an exact duplicate: run extraction, fingerprint check, and optional embedding similarity.

Expected impact:
- Large reduction in OpenRouter cost and latency for replays and repeated feeds.

Acceptance criteria:
- Exact duplicates (same title+content) do not trigger extraction.
- Duplicate behavior remains consistent (status, duplicate_of, duplicate_score).

B. Reduce extraction tokens and make output more deterministic
- Shorten the system prompt by:
  - Removing duplicated warnings.
  - Removing long calibration sections that are not directly used by the pipeline.
  - Keeping only: output schema, event list, and strict anti-hallucination rules.
- Reduce `max_tokens` (start with 400-600) and tighten JSON schema expectations.

Expected impact:
- Lower cost and latency; fewer partial JSON failures.

Acceptance criteria:
- Extraction still populates required fields for graph writes.
- JSON parsing error rate does not increase.

C. Pass precomputed candidate tickers to the LLM
- Ingest already has access to an instrument universe via Neo4j (used for regex fallback).
- Use a cheap pre-pass:
  - Regex scan for uppercase ticker-like tokens.
  - Or universe scan for known tickers found in the text.
- Provide a small "candidate_tickers" list to the extraction prompt.

Goal:
- Reduce hallucinated tickers and reduce reasoning work.

Acceptance criteria:
- Ticker false positive rate decreases in validation reports.

D. Reduce per-document overhead in simulation ingestion
- Replace per-document subprocess calls with a single Python HTTP client that:
  - Initializes one MCP session once.
  - Streams tool calls for many documents.
  - Uses bounded concurrency (N workers) on the client side.

Expected impact:
- Higher throughput and less CPU overhead on the orchestrator.

Acceptance criteria:
- Simulation ingestion time decreases for N=200 documents.
- No increase in ingestion failures.

E. Add explicit concurrency limits around OpenRouter and embeddings
- Add a process-wide semaphore (or bounded executor) so ingestion cannot create unbounded concurrent LLM calls.
- Apply separately to:
  - Extraction calls
  - Embedding calls

Expected impact:
- Reduced timeouts and more stable throughput under parallel ingestion.

Acceptance criteria:
- Parallel ingest (10 workers) does not cause elevated 5xx rates.

### 3.2 Medium-term improvements (1-2 weeks, moderate risk)

A. Add an ingest batch API/tool
Add a new MCP tool (or HTTP endpoint) for batch ingest:
- Input: list of documents (title, content, source_guid, optional metadata)
- Behavior:
  - Reuse one auth context.
  - Reuse sessions/clients.
  - Perform bulk Neo4j writes with UNWIND.
  - Perform bulk Chroma upserts with precomputed embeddings.

Expected impact:
- Lower per-document overhead and much better throughput.

Risks:
- Needs careful per-item error reporting and partial success semantics.

Acceptance criteria:
- Batch ingest of 100 docs is faster than 100 single ingests by at least 3x.
- Per-document results are returned and persist correctly.

B. Separate "store" from "enrich" (optional fast path)
Define two ingestion modes:
- Mode 1 (fast): store doc + cheap dedupe + minimal indexing, return success.
- Mode 2 (enrich): run extraction + graph updates + full embedding.

Implementation direction:
- Persist a "needs_enrichment" flag.
- Run enrichment asynchronously via a worker process.

Expected impact:
- Ingestion acknowledgement latency becomes stable and bounded.

Risks:
- Eventual consistency: graph edges appear later.

Acceptance criteria:
- Fast mode returns in under 500ms for typical docs (excluding downstream outages).
- Enrichment worker catches up and updates graph within SLA.

C. Make duplicate detection fully persistent and cross-worker
Today, duplicate detection uses:
- In-memory indexes (per process)
- Plus best-effort graph lookups for hash/fingerprint
- Plus Chroma similarity queries

Recommendation:
- Treat Neo4j as the system of record for exact duplicates (content_hash, story_fingerprint).
- Make in-memory caches best-effort only.
- Ensure content_hash and story_fingerprint are indexed/constrainted for fast lookup.

Expected impact:
- Correctness and consistency under multi-process scaling.

Acceptance criteria:
- Duplicate checks behave consistently across multiple server workers.

D. Reduce embedding cost with doc-level embeddings
Current behavior:
- Chunk embeddings are stored for semantic search.

Optimization:
- Store a separate "doc-level embedding" (title + summary or first N chars) used for:
  - Duplicate similarity checks
  - Fast coarse retrieval
- Keep chunk embeddings only when needed (or for documents above an impact threshold).

Expected impact:
- Lower OpenRouter embedding spend and faster ingestion.

Acceptance criteria:
- Query quality remains acceptable for IPS scenarios.

### 3.3 Longer-term redesign (2-6 weeks, higher impact)

A. Convert blocking dependencies to async or isolate in worker processes
Options:
1. Keep server handlers async, run all blocking work in a bounded threadpool.
2. Convert to async clients:
   - httpx.AsyncClient for OpenRouter
   - Neo4j async driver
   - Chroma async HTTP client (if available) or isolate behind a local service

Expected impact:
- Real concurrency with a single worker and reduced event loop blocking.

B. Introduce a job queue for ingestion/enrichment
- Use a durable queue (Redis, RabbitMQ, or Postgres-backed) for enrichment work.
- Ensure idempotency keys so retries are safe.

Expected impact:
- Improved resilience and controllable backpressure.

C. Improve idempotency and external identifiers
Add first-class support for:
- `external_id` (provider GUID), `published_at`, `source_name`
- Idempotent upsert semantics by (source_guid, external_id) or (content_hash)

Expected impact:
- Safer replays and easier reconciliation.

## 4. Prompt Optimization Details (Extraction)

### 4.1 Goals
- Reduce token count and latency.
- Reduce ticker hallucinations.
- Improve deterministic schema compliance.

### 4.2 Recommended prompt structure
System prompt (short):
- Strict policy: facts only, no guessing.
- Output schema only.
- Short event list.

User prompt (dynamic):
- Title
- Published timestamp (if available)
- Source name
- Candidate tickers list (optional)
- Content (possibly truncated):
  - Start with first 2000-4000 chars + last 500-1000 chars if long.

Rationale:
- Many financial stories contain the actionable details early (headline + lede).
- Tail content often contains boilerplate.

### 4.3 Multi-pass extraction (optional)
If cost pressure is high:
- Pass 1: cheap classifier returns {event_type, impact_tier, candidate tickers}.
- Pass 2: only run full extraction when impact_tier >= SILVER or when tickers are present.

## 5. System Guardrails and Observability

A. Instrument per-stage latency
Add structured timing logs/metrics around:
- source validation
- language detection
- extraction
- duplicate check (hash/fingerprint/embedding)
- file store save
- chroma upsert
- neo4j writes

B. Backpressure
- Global semaphores for extraction and embeddings.
- Per-request timeouts and bounded retries.

C. Failure semantics
Decide and document:
- Which failures should fail ingestion vs degrade gracefully.
- For example:
  - If Chroma is down: store document, mark "embedding_pending".
  - If Neo4j is down: store document, mark "graph_pending".

## 6. Suggested Rollout Plan

1. Implement quick win 3.1.A (hash-before-extraction) and add stage timing logs.
2. Tune prompt length and max_tokens, validate extraction accuracy against simulation reports.
3. Replace simulation ingest subprocess approach with a session-reusing client.
4. Add concurrency limits and run a controlled parallel ingest test.
5. Consider batch ingest and/or async enrichment if ingestion latency is still too high.

## 7. Open Questions (Need Product/Engineering Decision)

1. Do we require "graph edges available immediately" on ingest, or is eventual consistency acceptable?
2. Are duplicates required to be fully indexed (Chroma + Neo4j), or can we store-only duplicates and link to canonical?
3. What are target SLAs for ingest latency and for enrichment catch-up?
4. Which ingestion sources are expected in production (n8n, RSS, vendor API), and do they provide stable external IDs?
