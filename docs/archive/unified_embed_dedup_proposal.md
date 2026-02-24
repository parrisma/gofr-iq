# Proposal: Unified Embed + Duplicate Detection

## Problem

Each document ingestion makes a **separate** embedding API call solely for duplicate detection,
then makes a **second** embedding API call to index the document chunks in ChromaDB.

Current per-document API calls:

| # | Call | Endpoint | Purpose |
|---|------|----------|---------|
| 1 | chat/completions | /chat/completions | Graph extraction (impact, events, instruments) |
| 2 | embeddings | /embeddings | Duplicate detection query (embed `title + content`) |
| 3 | embeddings | /embeddings | ChromaDB chunk indexing (embed N chunks) |

Call #2 is redundant -- we can fold it into call #3 and use the resulting embedding
for the duplicate search without a separate round-trip.

Additionally, duplicates are currently stored and indexed just like originals (flagged
but not skipped). This wastes storage and ChromaDB/Neo4j capacity.

## Proposed Changes

### Change 1: Merge duplicate detection into embed_document

Add an `embed_and_check_duplicate` method to `EmbeddingIndex` that:

1. Chunks the document (produces N texts)
2. Prepends the full-text query (`title + " " + content[:500]`) as an extra item in the batch
3. Makes a **single** `POST /embeddings` call for N+1 texts
4. Uses embedding[0] to call `search_by_embedding()` (ChromaDB vector query, no API call)
5. Returns both the duplicate result AND the precomputed chunk embeddings

```python
# New method on EmbeddingIndex
@dataclass
class EmbedAndCheckResult:
    """Result of combined embed + duplicate check."""
    duplicate_result: DuplicateResult      # from vector similarity search
    chunk_ids: list[str]                   # chunk IDs (empty if not stored)
    embeddings: list[list[float]] | None   # precomputed chunk embeddings

def embed_and_check_duplicate(
    self,
    document_guid: str,
    title: str,
    content: str,
    group_guid: str,
    source_guid: str,
    language: str,
    metadata: dict | None = None,
    similarity_threshold: float = 0.85,
    time_window_hours: int = 48,
    store: bool = True,
) -> EmbedAndCheckResult:
    """Embed document and check for duplicates in a single API call.

    1. Chunk document
    2. Embed all chunks + duplicate-query text in one batch
    3. Search ChromaDB with the query embedding (no extra API call)
    4. Optionally store chunks to ChromaDB

    Args:
        ...
        store: If False, return embeddings without storing.
               Caller can decide based on duplicate result.
    """
```

### Change 2: Skip-duplicate mode in IngestService

Add a `skip_duplicates` flag to `IngestService` (default `False` for backward
compatibility). When enabled:

- If the combined embed+check detects a duplicate, the document is **not**
  stored to file, ChromaDB, or Neo4j.
- `IngestResult` is returned with `status=DUPLICATE` and no side effects.
- Hash and fingerprint checks still run before the embedding call (they are free).

```python
@dataclass
class IngestService:
    ...
    skip_duplicates: bool = False   # NEW: drop duplicates instead of storing them
```

New ingest flow with `skip_duplicates=True`:

```
IngestService.ingest()
  |-- 1. Validate source
  |-- 2. Validate word count
  |-- 3. Generate GUID, detect language
  |-- 4. Hash duplicate check (free, Neo4j + in-memory)
  |       -> if duplicate: return DUPLICATE immediately (no API calls)
  |-- 5. Fingerprint duplicate check (free, requires extraction)
  |       -> if duplicate: return DUPLICATE immediately
  |-- 6. LLM graph extraction (chat/completions -- unchanged)
  |-- 7. Combined embed + semantic duplicate check (ONE embeddings call)
  |       -> if duplicate AND skip_duplicates: return DUPLICATE (no store)
  |       -> if duplicate AND !skip_duplicates: store with duplicate_of flag (current behavior)
  |       -> if not duplicate: store chunks using precomputed embeddings
  |-- 8. Store to file, Neo4j, apply extraction
```

### Change 3: Reorder hash/fingerprint checks before LLM extraction

Currently hash and fingerprint checks happen *after* the LLM extraction call
because fingerprinting needs extraction output (tickers + event type).

Optimization: split duplicate detection into two phases:

- **Phase A** (before LLM, free): hash-only check against Neo4j + in-memory index.
  Exact duplicates are caught before spending on the extraction call.
- **Phase B** (after LLM): fingerprint check + semantic check (merged into embedding).

This saves the extraction call (~5k tokens) for exact-duplicate documents.

## API Call Impact

### Before (per document)

| Call | Tokens | Cost |
|------|--------|------|
| Graph extraction (chat/completions) | ~5,500 | $$$ |
| Duplicate query (embeddings) | ~200 | $ |
| Chunk indexing (embeddings) | ~1,500 | $ |
| **Total** | **~7,200** | |

### After -- not duplicate (per document)

| Call | Tokens | Cost |
|------|--------|------|
| Graph extraction (chat/completions) | ~5,500 | $$$ |
| Combined embed+check (embeddings) | ~1,700 | $ |
| **Total** | **~7,200** | |

API calls drop from 3 to 2. Token count stays the same (the query text is a
small addition to the chunk batch). Net saving: **1 API round-trip per document**.

### After -- duplicate with skip_duplicates=True

| Call | Tokens | Cost |
|------|--------|------|
| Graph extraction (chat/completions) | ~5,500 | $$$ |
| Combined embed+check (embeddings) | ~1,700 | $ |
| **Total** | **~7,200** | |

Same API calls as non-duplicate, but **no file/ChromaDB/Neo4j writes**.
Storage and index pollution eliminated.

If it is an exact hash duplicate (phase A), savings are even larger:

| Call | Tokens | Cost |
|------|--------|------|
| (none) | 0 | free |
| **Total** | **0** | |

### Batch impact (1000 documents, ~5% duplicate rate)

| Metric | Before | After (skip=True) |
|--------|--------|--------------------|
| API calls | ~3,000 | ~2,000 |
| Embedding API calls saved | -- | 1,000 |
| Exact-dup extraction calls saved | -- | ~25 (hash hits) |
| Files stored | 1,000 | ~950 |
| ChromaDB vectors | ~6,000 | ~5,700 |
| Neo4j document nodes | 1,000 | ~950 |

## Files Changed

| File | Change |
|------|--------|
| `app/services/embedding_index.py` | Add `EmbedAndCheckResult`, `embed_and_check_duplicate()` method |
| `app/services/ingest_service.py` | Add `skip_duplicates` flag, reorder hash check before extraction, replace separate embed + dup-check with `embed_and_check_duplicate()` |
| `app/services/duplicate_detector.py` | Add `check_with_embedding()` that accepts precomputed embedding instead of calling `search()` |
| `app/mcp_server/mcp_server.py` | Wire `skip_duplicates` from config/env var `GOFR_IQ_SKIP_DUPLICATES` |
| `test/test_ingest_service.py` | Test both modes, verify no API call for hash duplicates, verify no storage for skip mode |
| `test/test_embedding_index.py` | Test `embed_and_check_duplicate()` |

## Configuration

New env var:

```
GOFR_IQ_SKIP_DUPLICATES=true   # default: false (backward compatible)
```

For the simulation pipeline, `run_simulation.sh` can pass `--skip-duplicates`
which sets this env var before starting the MCP server.

## Backward Compatibility

- `skip_duplicates=False` (default): behavior is identical to today except the
  duplicate detection embedding is folded into the chunk embedding call (invisible
  optimization, no behavioral change).
- `skip_duplicates=True`: opt-in. Duplicates are rejected instead of stored.
  IngestResult still reports status=DUPLICATE with duplicate_of and score so callers
  can log/report.

## Risks

1. **Reordering hash check before extraction**: the hash check does not need extraction
   output, so this is safe. Fingerprint check still happens after extraction.

2. **Single batch embedding**: the query text (~500 chars) is small relative to the
   chunk batch. OpenRouter's batch limit is large (100+ texts). No risk of exceeding it.

3. **skip_duplicates data loss**: duplicates are intentionally dropped. Documents can
   always be re-ingested if the flag is changed. The append-only contract is preserved
   when the flag is off.

4. **Test coverage**: existing duplicate detection tests continue to pass unchanged.
   New tests cover the merged path and the skip mode.
