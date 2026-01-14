# Document Ingestion Pipeline

The ingestion pipeline processes news articles from external sources into the repository, extracting entities, detecting duplicates, and indexing for search and analysis.

---

## Overview

**GOFR-IQ** ingestion is optimized for **append-only storage** with **immutable documents** and **group-scoped access**. Every document is validated, deduplicated, and indexed across three storage backends simultaneously.

### Key Design Principles

1. **Immutability** - Documents never modified; new versions create new records linked to predecessors
2. **Append-only** - No hard deletes; documents marked as superseded but preserved
3. **Group-scoped** - All documents belong to exactly one group (for access control)
4. **Deduplication** - Documents flagged as duplicates but stored (not discarded)
5. **Transactional** - All-or-nothing: succeeds fully or rolls back completely
6. **Concurrent** - Supports parallel ingestion with thread-safe operations

---

## Full Ingestion Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 1: INPUT VALIDATION                                               │
│  ├─ Validate source_guid exists                                         │
│  ├─ Check user has write access to group                                │
│  └─ Verify word count ≤ 20,000 words                                    │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 2: LANGUAGE DETECTION                                             │
│  ├─ Auto-detect language (if not provided)                              │
│  ├─ Supports 100+ languages                                             │
│  ├─ Special handling for APAC languages                                 │
│  └─ Store detected flag for audit trail                                 │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 3: DUPLICATE DETECTION                                            │
│  ├─ Hash-based exact match detection (SHA-256)                          │
│  ├─ Cosine similarity near-duplicate detection                          │
│  ├─ Configurable threshold (default 0.95)                               │
│  └─ Flag but store duplicates (append-only)                             │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 4: GENERATE METADATA                                              │
│  ├─ Generate UUID v4 for document GUID                                  │
│  ├─ Record creation timestamp (UTC)                                     │
│  ├─ Set version = 1                                                     │
│  └─ Store user-provided metadata                                        │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 5: CANONICAL STORAGE (FILE STORE)                                 │
│  ├─ Serialize to JSON with all metadata                                 │
│  ├─ Store at: data/storage/documents/{group}/{YYYY-MM-DD}/{guid}.json   │
│  ├─ Create date-based partitions for efficiency                         │
│  └─ Verify successful write before proceeding                           │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 6: VECTOR INDEXING (CHROMADB) - PARALLEL                          │
│  ├─ Embed document using OpenRouter embeddings                          │
│  ├─ Chunk content for optimal embeddings                                │
│  ├─ Create group-specific collection                                    │
│  ├─ Store metadata (title, date, language, source)                      │
│  └─ On fail: ROLLBACK ALL                                               │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 7: GRAPH INDEXING (NEO4J) - PARALLEL                              │
│  ├─ Create Document node                                                │
│  ├─ Link to Source node (PRODUCED_BY)                                   │
│  ├─ Link to Group node (IN_GROUP)                                       │
│  └─ On fail: ROLLBACK ALL                                               │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 8: LLM EXTRACTION (OPENROUTER API) - OPTIONAL                     │
│  ├─ Extract entities (companies, instruments)                           │
│  ├─ Identify event type (earnings, M&A, guidance, etc.)                 │
│  ├─ Calculate impact score (0-100) and tier                             │
│  ├─ Estimate price impact magnitude                                     │
│  └─ Continue on failure (not transactional)                             │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 9: GRAPH ENRICHMENT (NEO4J) - OPTIONAL                            │
│  ├─ Create entity nodes (Company, Instrument, EventType)                │
│  ├─ Create relationships (MENTIONS, AFFECTS)                            │
│  ├─ Set document impact properties                                      │
│  └─ Continue on failure (non-critical)                                  │
└─────────────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 10: RETURN RESULT                                                 │
│  ├─ Status: SUCCESS | DUPLICATE | FAILED                                │
│  ├─ Include: guid, language, duplicate_of, extraction                   │
│  └─ Audit log all operations                                            │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Details

### Step 1: Input Validation

**Validates**:
- Source exists in `SourceRegistry` (sources are global)
- User has write access to target group
- Document word count ≤ max (default 20,000)

**Returns**:
- `SourceNotFoundError` if source not found
- `WordCountError` if content too long

**Code**:
```python
# Validate source exists (sources are global)
source = source_registry.get(source_guid)
if source is None:
    raise SourceNotFoundError(source_guid)

# Validate word count
word_count = count_words(content)
if word_count > self.max_word_count:
    raise WordCountError(word_count, self.max_word_count)
```

### Step 2: Language Detection

**Detection Process**:
1. If language provided → use provided language
2. If not provided → auto-detect using `LanguageDetector`

**Auto-Detection**:
- Uses natural language processing
- Supports 100+ languages
- Special handling for APAC languages:
  - `en` - English
  - `zh` - Simplified Chinese
  - `zh-Hant` - Traditional Chinese
  - `ja` - Japanese
  - `ko` - Korean
  - `th` - Thai
  - `vi` - Vietnamese
  - etc.

**Output**:
```python
{
  "language": "en",
  "language_detected": true,  # false if provided
  "confidence": 0.98,  # from LanguageDetector
  "is_apac": true
}
```

### Step 3: Duplicate Detection

**Two-Stage Detection**:

#### Stage 1: Exact Match (SHA-256 Hash)
- Normalizes text: lowercase, remove extra whitespace
- Computes SHA-256 hash of normalized content
- Checks against hash cache for exact matches
- Fast O(1) lookup

#### Stage 2: Near-Duplicate (Cosine Similarity)
- If no exact match found
- Tokenizes both documents
- Computes TF-IDF vectors
- Calculates cosine similarity
- Configurable threshold: 0.95 (default)

**Behavior** (Append-Only):
- ✅ Duplicate documents **still stored** (not discarded)
- ✅ Flagged with `duplicate_of: original_guid`
- ✅ `duplicate_score` records similarity (0-1)
- ✅ Status returned as `DUPLICATE` (not `FAILED`)

**Configuration**:
```bash
export GOFR_IQ_DUPLICATE_THRESHOLD=0.95  # [0.0-1.0]
export GOFR_IQ_MAX_WORD_COUNT=20000
```

**Output**:
```python
{
  "is_duplicate": true,
  "duplicate_of": "550e8400-...",  # Original document GUID
  "score": 0.987,  # Similarity score
  "method": "similarity"  # "hash" or "similarity"
}
```

### Step 4: Metadata Generation

**Generated Fields**:
- `guid` - UUID v4 for uniqueness
- `version` - Document version (1 for new)
- `created_at` - ISO timestamp (UTC)
- `updated_at` - Same as created_at (initial)
- `language` - Auto-detected or provided
- `word_count` - Validated word count

**Document Schema**:
```json
{
  "guid": "550e8400-e29b-41d4-a716-446655440000",
  "version": 1,
  "source_guid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "group_guid": "12345678-1234-1234-1234-123456789abc",
  "created_at": "2025-12-08T10:30:00Z",
  "updated_at": "2025-12-08T10:30:00Z",
  "title": "Market Analysis Q4 2025",
  "content": "Full text content... (validated ≤ 20K words)",
  "language": "en",
  "language_detected": true,
  "word_count": 5432,
  "duplicate_of": null,
  "duplicate_score": 0.0,
  "metadata": {
    "author": "John Smith",
    "region": "APAC",
    "sectors": ["technology", "finance"],
    "companies": ["AAPL", "GOOGL"],
    "impact_score": 72.5,
    "impact_tier": "GOLD",
    "event_type": "EARNINGS_BEAT"
  }
}
```

### Step 5: Canonical Storage (File Store)

**Purpose**: Single source of truth

**Storage Location**:
```
data/storage/documents/{group_guid}/{YYYY-MM-DD}/{document_guid}.json
```

**Example Path**:
```
data/storage/documents/12345678-1234-1234-1234-123456789abc/2025-12-08/550e8400-e29b-41d4-a716-446655440000.json
```

**Properties**:
- **Immutable** - Never modify existing files
- **Append-only** - New versions create new files
- **Date-partitioned** - Efficient queries by date range
- **Group-scoped** - All documents in own group folder
- **Persistent** - Survives restarts

**Verification**:
- File write succeeds before proceeding to indexing
- File read succeeds after write (verify persistence)
- Document accessible via `DocumentStore` API

### Step 6: Vector Indexing (ChromaDB)

**Purpose**: Enable semantic similarity search

**Process**:
1. **Chunking** - Split document into chunks (if needed)
   - Overlap for context preservation
   - Configurable chunk size
2. **Embedding** - Convert text to vectors using LLM
   - Model: `qwen/qwen3-embedding-8b` (default)
   - Dimensions: 1536
   - Batch processing for efficiency
3. **Metadata** - Store alongside vectors
   - Document title
   - Creation date
   - Language
   - Source GUID
   - Custom metadata
4. **Collection** - Group by organization
   - One collection per group
   - Isolation for access control
   - Separate similarity searches

**ChromaDB Metadata Schema**:
```python
{
  "document_guid": "550e8400-...",
  "group_guid": "12345678-...",
  "source_guid": "7c9e6679-...",
  "title": "Market Analysis Q4 2025",
  "created_at": "2025-12-08T10:30:00Z",
  "language": "en",
  "region": "APAC",
  "sectors": "technology,finance",
  "companies": "AAPL,GOOGL"
}
```

**Storage**:
```
data/storage/chromadb/
├── {group_guid}.db
└── {group_guid}/
    └── (vector data)
```

**Error Handling**:
- If ChromaDB indexing fails → **ROLLBACK**
- Remove from file store (Step 5 reversed)
- Return `FAILED` status with error message

### Step 7: Graph Indexing (Neo4j)

**Purpose**: Enable entity relationships and traversal

**Nodes Created**:
- **Document** - The document itself
  - Properties: guid, title, created_at, language
  - Labels: `Document`

**Relationships Created**:
- `PRODUCED_BY` - Document → Source
- `IN_GROUP` - Document → Group

**Neo4j Query**:
```cypher
CREATE (doc:Document {
  guid: $guid,
  title: $title,
  language: $language,
  created_at: $created_at
})
CREATE (doc)-[:PRODUCED_BY]->(source:Source {guid: $source_guid})
CREATE (doc)-[:IN_GROUP]->(group:Group {guid: $group_guid})
```

**Storage**:
```
data/neo4j/
├── data/
└── (graph data)
```

**Error Handling**:
- If Neo4j indexing fails → **ROLLBACK**
- Remove from ChromaDB (Step 6 reversed)
- Remove from file store (Step 5 reversed)
- Return `FAILED` status with error message

### Step 8: LLM Extraction (Optional)

**Purpose**: Extract entities and calculate impact scores

**Uses OpenRouter API**:
- Chat model: `anthropic/claude-opus-4` (default)
- Prompt: System prompt + document content
- Temperature: 0.1 (low for consistency)
- Output: JSON with parsed entities

**Extracted Information**:

| Field | Type | Example |
|-------|------|---------|
| `primary_event` | EventType | earnings_beat, m&a_announce |
| `impact_score` | float | 72.5 (0-100) |
| `impact_tier` | enum | GOLD, PLATINUM, SILVER, BRONZE, STANDARD |
| `event_type_code` | string | EARNINGS_BEAT |
| `instruments` | list | [{ticker: "AAPL", direction: "UP", magnitude: "HIGH"}] |
| `companies` | list | [{name: "Apple", ticker: "AAPL"}] |
| `sectors` | list | ["technology", "consumer"] |
| `key_points` | list | ["Beat expectations", "Raised guidance"] |

**Extraction Prompt**:
```
System: You are a financial analyst. Extract key information from news.

User: [Document title and content]

Expected JSON:
{
  "primary_event": "earnings_beat",
  "impact_score": 72.5,
  "impact_tier": "GOLD",
  "instruments": [...],
  "companies": [...],
  "sectors": [...],
  "key_points": [...]
}
```

**Error Handling**:
- If LLM API fails → **Continue** (extraction optional)
- Return default extraction result
- Ingestion still succeeds with `status: SUCCESS`

**Performance**:
- LLM API calls are slow (2-5 seconds per document)
- Bottleneck for high-volume ingestion
- Consider async processing for bulk ingestion

### Step 9: Graph Enrichment (Optional)

**Purpose**: Link document to entities and set impact properties

**Actions**:
1. **Set Document Impact**:
   - `impact_score` - Numeric score (0-100)
   - `impact_tier` - Enumerated tier (PLATINUM/GOLD/SILVER/BRONZE/STANDARD)
   - `event_type_code` - Code like "EARNINGS_BEAT"
   - `decay_lambda` - Time decay rate by tier

2. **Create Entity Nodes**:
   - Company nodes (if not existing)
   - Instrument nodes (if not existing)
   - EventType nodes (if not existing)

3. **Create Relationships**:
   - `MENTIONS` - Document → Company
   - `AFFECTS` - Document → Instrument (with direction/magnitude)
   - `TRIGGERED_BY` - Document → EventType

**Neo4j Queries**:
```cypher
# Set impact
MATCH (doc:Document {guid: $doc_guid})
SET doc.impact_score = $impact_score,
    doc.impact_tier = $tier,
    doc.event_type = $event_code,
    doc.decay_lambda = $decay_lambda

# Create AFFECTS relationship
MATCH (doc:Document {guid: $doc_guid}),
      (inst:Instrument {ticker: $ticker})
CREATE (doc)-[:AFFECTS {direction: $direction, magnitude: $magnitude}]->(inst)
```

**Error Handling**:
- If enrichment fails → **Continue** (non-critical)
- Missing entities created on-demand
- Ingestion still succeeds

### Step 10: Return Result

**IngestResult Schema**:
```python
{
  "guid": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",  # success | duplicate | failed
  "language": "en",
  "language_detected": true,
  "duplicate_of": null,
  "duplicate_score": null,
  "word_count": 5432,
  "created_at": "2025-12-08T10:30:00Z",
  "error": null,
  "extraction": {
    "primary_event": "earnings_beat",
    "impact_score": 72.5,
    "impact_tier": "GOLD",
    "instruments": [...],
    "companies": [...],
    "sectors": [...]
  }
}
```

**Status Values**:
- **SUCCESS** - Document ingested, indexed, and extracted
- **DUPLICATE** - Document is duplicate but still stored
- **FAILED** - Validation/indexing failed, document rolled back

---

## Ingestion Modes

### Single Document Ingestion

**Method**: `ingest()`

```python
result = ingest_service.ingest(
    title="Apple Reports Q4 Earnings Beat",
    content="Apple Inc. reported Q4 earnings...",
    source_guid="7c9e6679-7425-40de-944b-e07fc1f90ae7",
    group_guid="12345678-1234-1234-1234-123456789abc",
    language="en",  # Optional, auto-detected if omitted
    metadata={
        "author": "John Smith",
        "region": "APAC",
        "sectors": ["technology"]
    }
)
```

**Returns**: Single `IngestResult`

### Batch Ingestion

**Method**: `ingest_batch()`

```python
documents = [
    DocumentCreate(
        title="...",
        content="...",
        source_guid="...",
        group_guid="...",
    ),
    # ... more documents
]

results = ingest_service.ingest_batch(
    documents=documents,
    stop_on_error=False  # Continue on errors
)
```

**Returns**: List of `IngestResult`

**Behavior**:
- Process documents sequentially
- Each document independent transaction
- `stop_on_error=True` stops on first failure
- `stop_on_error=False` (default) continues despite errors

---

## Error Handling & Rollback

### Transactional Semantics (Steps 5-7)

If **any** of these fail, **all** are rolled back:
1. File store write (Step 5)
2. ChromaDB indexing (Step 6)
3. Neo4j indexing (Step 7)

**Rollback Strategy**:
1. **File Store** - Remove written document
2. **ChromaDB** - Remove embeddings and metadata
3. **Neo4j** - Delete document node and relationships

**Atomicity**: Guaranteed via try/catch with cleanup

**Example**:
```python
try:
    document_store.save(doc)              # Step 5
    embedding_index.embed_document(...)  # Step 6
    graph_index.create_document_node(...) # Step 7
except Exception as e:
    # Rollback in reverse order
    document_store.delete(guid, group, created_at)
    embedding_index.delete_document(guid)
    graph_index.delete_node(NodeLabel.DOCUMENT, guid)
    return IngestResult(..., status=FAILED, error=str(e))
```

### Non-Transactional Steps (8-9)

LLM extraction and graph enrichment **do not** trigger rollback:
- Failures logged but ignored
- Ingestion succeeds anyway
- Return partial `extraction` result

**Rationale**: These steps are enrichments, not critical for core functionality

---

## Performance Characteristics

### Throughput

| Stage | Time | Bottleneck |
|-------|------|-----------|
| Validation | 10ms | File I/O for source check |
| Language Detection | 50ms | NLP model inference |
| Duplicate Detection | 30ms | Similarity calculation |
| File Storage | 5ms | Disk write |
| ChromaDB Indexing | 500-2000ms | LLM embedding API |
| Neo4j Indexing | 100ms | Graph operations |
| LLM Extraction | 2000-5000ms | OpenRouter API latency |
| **Total (Single Doc)** | **2.7-7.1s** | **LLM extraction** |

### Scaling

**Throughput** (single thread): ~10-20 documents/second

**Optimization**:
- Batch embeddings (reduce API overhead)
- Cache LLM results for common event types
- Use cheaper embeddings model for preview
- Async extraction (process while users search)

---

## Best Practices

### 1. Pre-Validate Inputs
```python
# Always check source exists before ingestion
source = source_registry.get(source_guid)
if not source:
    raise ValueError(f"Source {source_guid} not found")

# Validate word count
if len(content.split()) > 20000:
    raise ValueError("Content exceeds 20,000 words")
```

### 2. Provide Metadata
```python
# Rich metadata enables better search and filtering
result = ingest_service.ingest(
    title="...",
    content="...",
    source_guid="...",
    group_guid="...",
    metadata={
        "author": "John Smith",
        "region": "APAC",
        "published_at": "2025-12-08T10:00:00Z",
        "sectors": ["technology", "finance"],
        "confidence": 0.95  # Custom fields supported
    }
)
```

### 3. Monitor LLM Costs
```python
# LLM extraction is the bottleneck and most expensive
# Disable for development/testing if needed

# Check if LLM is configured
if ingest_service.llm_service.is_available:
    # Extraction will run
    pass
else:
    # Extraction skipped (LLM not configured)
    pass
```

### 4. Handle Duplicates Gracefully
```python
# Duplicates are stored, not rejected
result = ingest_service.ingest(...)

if result.status == IngestStatus.DUPLICATE:
    # Document is duplicate but was stored
    print(f"Duplicate of {result.duplicate_of}")
    print(f"Similarity: {result.duplicate_score}")
```

### 5. Batch Ingestion
```python
# For bulk ingestion, use batch method
# More efficient error handling and logging

results = ingest_service.ingest_batch(
    documents=documents,
    stop_on_error=False
)

successes = [r for r in results if r.status == IngestStatus.SUCCESS]
duplicates = [r for r in results if r.status == IngestStatus.DUPLICATE]
failures = [r for r in results if r.status == IngestStatus.FAILED]

print(f"Success: {len(successes)}, Duplicates: {len(duplicates)}, Failed: {len(failures)}")
```

---

## Integration Examples

### From Web API (REST)

```python
@app.post("/ingest")
async def ingest_document(doc: DocumentCreate, user: CurrentUser):
    result = ingest_service.ingest(
        title=doc.title,
        content=doc.content,
        source_guid=doc.source_guid,
        group_guid=user.primary_group,  # Use user's primary group
        language=doc.language,
        metadata=doc.metadata
    )
    return result.to_dict()
```

### From MCP (Model Context Protocol)

```python
@mcp_server.tool()
def ingest_news_article(
    title: str,
    content: str,
    source_id: str,
    group_id: str,
    language: str | None = None
) -> dict:
    """Ingest a news article into the repository."""
    result = ingest_service.ingest(
        title=title,
        content=content,
        source_guid=source_id,
        group_guid=group_id,
        language=language
    )
    return result.to_dict()
```

### Batch Import Script

```python
import json

# Load documents from JSON file
with open("articles.jsonl") as f:
    docs = [DocumentCreate(**json.loads(line)) for line in f]

# Ingest with progress tracking
results = ingest_service.ingest_batch(docs, stop_on_error=False)

# Report results
success_count = sum(1 for r in results if r.is_success)
dup_count = sum(1 for r in results if r.is_duplicate)
fail_count = sum(1 for r in results if r.is_failed)

print(f"Ingested: {success_count}, Duplicates: {dup_count}, Failed: {fail_count}")
```

---

## Related Documentation

- [Architecture Overview](overview.md)
- [Hybrid Search](../features/hybrid-search.md)
- [Configuration Reference](../getting-started/configuration.md)
- [Authentication Architecture](authentication.md)
- [Quick Start Guide](../getting-started/quick-start.md)
