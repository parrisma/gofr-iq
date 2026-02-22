# Document Ingest -- LLM API Call Analysis

## Overview

Each document ingestion triggers **two categories** of OpenRouter API call:

1. **Chat completion** -- graph entity extraction (1 call per document)
2. **Embedding generation** -- ChromaDB vector indexing (1+ calls per document, depends on chunk count)

Both hit `https://openrouter.ai/api/v1` via `LLMService` (httpx, sync, with retry).

---

## Ingestion Flow (step-by-step)

```
IngestService.ingest()
  |
  |-- 1. Validate source_guid exists (SourceRegistry lookup)
  |-- 2. Validate word count (<= 20,000 words)
  |-- 3. Generate UUID v4 document GUID
  |-- 4. Detect language (local, lingua-py -- NO LLM)
  |-- 5. Build provisional Document object
  |
  |-- 6. *** LLM CALL #1: Graph Extraction ***
  |       _extract_graph_entities(doc)
  |         -> POST /chat/completions
  |
  |-- 7. Duplicate detection (hash + optional ChromaDB similarity)
  |       DuplicateDetector.check()
  |         -> ChromaDB search (uses EXISTING embeddings, may trigger
  |            embedding of the query text = 1 embedding API call)
  |
  |-- 8. Store document to canonical file store
  |
  |-- 9. *** LLM CALL #2: Embedding Generation ***
  |       EmbeddingIndex.embed_document(doc)
  |         -> chunks document (default: 1000 char chunks, 200 overlap)
  |         -> POST /embeddings (once per batch of up to 100 chunks)
  |
  |-- 10. Create Neo4j Document node + Source node
  |
  |-- 11. Apply extraction to graph
  |        _augment_extraction_with_regex_tickers() -- NO LLM, regex only
  |        _apply_extraction_to_graph()
  |          -> MERGE EventType, Instrument, Company nodes
  |          -> CREATE TRIGGERED_BY, AFFECTS, MENTIONS relationships
  |
  |-- 12. Register with duplicate detector for future checks
```

---

## LLM API Calls -- Detail

### Call 1: Graph Entity Extraction (chat completion)

| Field | Value |
|-------|-------|
| **File** | `app/services/ingest_service.py` :: `_extract_graph_entities()` (line ~258) |
| **Endpoint** | `POST /chat/completions` |
| **Model** | `meta-llama/llama-3.1-70b-instruct` (config: `GOFR_IQ_LLM_MODEL`) |
| **Temperature** | 0.1 |
| **Max tokens** | 1,000 |
| **JSON mode** | Yes (`response_format: json_object`) |
| **System prompt** | `GRAPH_EXTRACTION_SYSTEM_PROMPT` (~4,500 tokens) in `app/prompts/graph_extraction.py` |
| **User prompt** | Title + source + published date + full article content |

**Purpose**: Analyze the news article and extract structured JSON containing:
- `impact_score` (0-100) and `impact_tier` (PLATINUM/GOLD/SILVER/BRONZE/STANDARD)
- `events[]` -- event type (EARNINGS_BEAT, M&A_ANNOUNCE, etc.) + confidence
- `instruments[]` -- affected tickers with direction (UP/DOWN/MIXED/NEUTRAL) and magnitude
- `companies[]` -- all company names mentioned (for MENTIONS relationships)
- `regions[]` -- geographic context
- `sectors[]` -- industry context
- `themes[]` -- controlled vocabulary tags (ai, semiconductor, ev_battery, etc.)
- `summary` -- one-line headline

**Response parsed by**: `parse_extraction_response()` in `app/prompts/graph_extraction.py`

**Used for**:
- Setting `impact_score` / `impact_tier` on the Document node in Neo4j
- Creating `TRIGGERED_BY` edges to EventType nodes
- Creating `AFFECTS` edges to Instrument nodes (with direction/magnitude)
- Creating `MENTIONS` edges to Company nodes
- Storing themes on the Document node
- Enriching ChromaDB metadata (impact_score, impact_tier)
- Computing `story_fingerprint` for duplicate detection

**Required?** Yes, when `graph_index` is configured (hard fail if LLM unavailable).

---

### Call 2: Embedding Generation

| Field | Value |
|-------|-------|
| **File** | `app/services/embedding_index.py` :: `embed_document()` (line ~416) -> `LLMEmbeddingFunction.__call__()` (line ~148) |
| **Endpoint** | `POST /embeddings` |
| **Model** | `qwen/qwen3-embedding-8b` (config: `GOFR_IQ_EMBEDDING_MODEL`) |
| **Batch size** | Up to 100 texts per API call |

**Purpose**: Generate vector embeddings for each document chunk to store in ChromaDB.

**Chunking**: `ChunkConfig(chunk_size=1000, chunk_overlap=200, min_chunk_size=100)`.
An average news article (~500-1500 words, ~3000-9000 chars) produces **3-9 chunks**.
Each chunk is embedded in a single batch call.

**Used for**:
- ChromaDB similarity search (query-time)
- Duplicate detection (semantic near-duplicate check)

**Required?** Yes, when `embedding_index` is configured.

---

### Call 2b: Duplicate Detection Query (embedding, conditional)

| Field | Value |
|-------|-------|
| **File** | `app/services/duplicate_detector.py` :: `check()` (line ~375) -> `EmbeddingIndex.search()` |
| **Endpoint** | `POST /embeddings` (via ChromaDB query path) |
| **Model** | Same embedding model (`qwen/qwen3-embedding-8b`) |

**Purpose**: Before storing, search ChromaDB for semantically similar existing documents.
The query text (`title + " " + content[:500]`) is embedded to find near-duplicates.

**Count**: 1 embedding call (single text) per ingest, only when `use_similarity_detection=True` and `embedding_index` is provided.

---

## Summary: API Calls Per Document

| Call | Type | Model | Count | Tokens (approx) |
|------|------|-------|-------|-----------------|
| Graph extraction | chat/completions | llama-3.1-70b-instruct | 1 | ~5k prompt + ~500 completion |
| Document embedding | embeddings | qwen3-embedding-8b | 1 | ~500-2000 tokens (all chunks batched) |
| Duplicate check query | embeddings | qwen3-embedding-8b | 0-1 | ~200 tokens |
| **Total per document** | | | **2-3** | **~5.5k-7.5k tokens** |

For a 200-document simulation batch: **~400-600 API calls**, **~1.1M-1.5M tokens**.

---

## Non-Ingest LLM Calls (for reference)

These are NOT part of the ingest flow but exist in the codebase:

| Caller | Type | Model | Purpose |
|--------|------|-------|---------|
| `mandate_enrichment.py` :: `extract_themes_from_mandate()` | chat/completions | llama-3.1-70b-instruct | Extract investment themes from client mandate text (runs when mandate_text is set/updated, not during doc ingest) |
| `client_tools.py` :: mandate embedding (~line 348, 2087, 2121) | embeddings | qwen3-embedding-8b | Embed client mandate text for vector similarity matching (runs when client profile is created/updated) |
| `query_service.py` :: chat_completion (~lines 901, 1238, 1652) | chat/completions | llama-3.1-70b-instruct | Query-time LLM calls (summary generation, not ingest) |

---

## Configuration Reference

| Env Var | Default | Purpose |
|---------|---------|---------|
| `GOFR_IQ_OPENROUTER_API_KEY` | (Vault: `gofr/config/api-keys/openrouter`) | API authentication |
| `GOFR_IQ_OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | API endpoint |
| `GOFR_IQ_LLM_MODEL` | `meta-llama/llama-3.1-70b-instruct` | Chat completion model |
| `GOFR_IQ_EMBEDDING_MODEL` | `qwen/qwen3-embedding-8b` | Embedding model |
| `GOFR_IQ_LLM_MAX_RETRIES` | 3 | Retry count on failure/rate-limit |
| `GOFR_IQ_LLM_TIMEOUT` | 60s | HTTP request timeout |

---

## Error Handling

- Rate limits (HTTP 429): exponential backoff with `Retry-After` header, up to `max_retries`.
- API errors (4xx/5xx): retried with backoff.
- Network errors (transport): retried with backoff.
- If extraction fails and `graph_index` is enabled: **hard fail** -- document is not ingested, file store is rolled back.
- If extraction fails and `graph_index` is not enabled: returns `create_default_result()` (STANDARD tier, no entities).
