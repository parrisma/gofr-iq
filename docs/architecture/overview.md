# Architecture Overview

**GOFR-IQ** is a hybrid search and ranking system for APAC brokerage news that combines semantic similarity search, graph-based entity relationships, and client-specific relevance scoring.

## System Purpose

Process news articles through:
1. **Ingestion** - Store, extract entities, detect duplicates
2. **Indexing** - Vector embeddings (ChromaDB), graph relationships (Neo4j)
3. **Search** - Hybrid semantic + graph search with group access control
4. **Ranking** - Client-specific relevance using portfolio holdings and impact scoring

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CLIENT INTERFACES                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │   MCP       │    │   MCPO      │    │   Web API   │                      │
│  │  (8080)     │    │  (8081)     │    │   (8082)    │                      │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                      │
│         │ Model Context    │ OpenAPI        │ REST                          │
│         │ Protocol         │ + SSE Events   │ + JSON                        │
└─────────┼──────────────────┼────────────────┼─────────────────────────────┘
          │                  │                │
          └──────────────────┼────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AUTH & ACCESS CONTROL LAYER                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  JWT Token Validation → Group Membership → Scope Enforcement        │    │
│  │  Backend: Vault (prod) / File (dev) / Memory (test)                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ INGEST SERVICE  │  │  QUERY SERVICE  │  │ SOURCE REGISTRY │
│                 │  │                 │  │                 │
│ • Validation    │  │ • Hybrid Search │  │ • CRUD Ops      │
│ • Extraction    │  │ • Scoring       │  │ • Permissions   │
│ • Deduplication │  │ • Graph Expand  │  │ • Trust Levels  │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CANONICAL STORAGE LAYER                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  File-based, immutable, append-only JSON storage                    │    │
│  │                                                                      │    │
│  │  data/storage/documents/{group}/{YYYY-MM-DD}/{guid}.json            │    │
│  │  data/storage/sources/{source_guid}.json                            │    │
│  │  data/storage/groups/{group_guid}.json                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    Neo4j        │  │   ChromaDB      │  │   LLM Service   │
│  (Graph Index)  │  │  (Embeddings)   │  │  (OpenRouter)   │
│                 │  │                 │  │                 │
│ • Entities      │  │ • Vector Search │  │ • Entity Extract│
│ • Relationships │  │ • Similarity    │  │ • Impact Score  │
│ • Client Feeds  │  │ • Group Filter  │  │ • Summarization │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## Core Components

### 1. Client Layer

Three server interfaces exposing identical functionality:

| Interface | Protocol | Port | Use Case |
|-----------|----------|------|----------|
| **MCP** | Model Context Protocol | 8080 | AI assistant integration (Claude, etc.) |
| **MCPO** | OpenAPI with SSE | 8081 | External apps needing OpenAPI spec |
| **Web** | REST/JSON | 8082 | Direct HTTP API access |

All interfaces share the same tool implementations under `app/tools/`.

### 2. Authentication Layer

**Token-based authentication** with group membership and scopes:

- **JWT Tokens** - Signed with `GOFR_IQ_JWT_SECRET`
- **Group Membership** - User belongs to 1+ groups (e.g., `apac-research`, `japan-desk`)
- **Scopes** - Permissions: `read`, `write`, `admin`
- **Backend** - Vault (prod), File (dev), Memory (test)

See [Authentication Architecture](authentication.md) for details.

### 3. Service Layer

#### IngestService
**Purpose**: Validate, extract, deduplicate, and store news documents.

**Flow**:
1. Validate source exists and user has `write` access
2. Check word count ≤ 20,000 words
3. Detect language (auto-detect or accept provided)
4. Check for duplicates (similarity > 0.95 threshold)
5. Store to canonical file store
6. Extract entities with LLM (companies, instruments, impact score)
7. Update ChromaDB with embeddings
8. Update Neo4j with graph relationships
9. Return `{ guid, status, language, duplicate_of?, extraction }`

**Dependencies**:
- `DocumentStore` - File storage
- `SourceRegistry` - Source validation
- `LanguageDetector` - Language detection
- `DuplicateDetector` - Similarity check
- `LLMService` - Entity extraction
- `EmbeddingIndex` - Vector storage
- `GraphIndex` - Graph updates

#### QueryService
**Purpose**: Hybrid search combining semantic similarity and graph context.

**Flow**:
1. Validate user's permitted groups
2. Execute ChromaDB similarity search (filtered by groups)
3. Apply metadata filters (date, region, sector, company, language)
4. Enrich with Neo4j graph context (related entities, relationships)
5. Calculate hybrid score: `semantic × 0.6 + trust × 0.2 + recency × 0.1 + graph × 0.1`
6. Apply client-specific ranking (portfolio holdings, watchlist)
7. Return ranked results with snippets

**Scoring Components**:
- **Semantic** (0.6) - Embedding similarity
- **Trust** (0.2) - Source trust level (high/medium/low)
- **Recency** (0.1) - Time decay factor
- **Graph** (0.1) - Related entity bonus

#### SourceRegistry
**Purpose**: CRUD operations for news sources with group permissions.

**Features**:
- Create/read/update sources
- Group-based access control (`read`, `write`, `admin` scopes)
- Trust level management (high/medium/low → score boost)
- Regional classification
- Language support list

#### GraphIndex (Neo4j)
**Purpose**: Store entity relationships and enable graph traversal.

**Node Types**:
- Document, Source, Company, Instrument, Sector, Region
- Client, Portfolio, Watchlist (for personalization)
- EventType, Index, Factor (for impact scoring)

**Key Relationships**:
- `PRODUCED_BY` - Document → Source
- `MENTIONS` - Document → Company/Instrument
- `AFFECTS` - Document → Instrument (with impact score)
- `HOLDS` / `WATCHES` - Client → Instrument (for relevance)
- `IN_GROUP` - All entities → Group (for access control)

See [Graph Design](graph-design.md) for schema details.

#### EmbeddingIndex (ChromaDB)
**Purpose**: Vector similarity search with group filtering.

**Features**:
- Stores document embeddings (1536-dim vectors from OpenRouter)
- Group-based collections (one collection per group)
- Metadata filtering (date, language, source, etc.)
- Similarity search with distance metrics
- Automatic chunking for large documents

**Storage**: Persistent local storage in `data/storage/chromadb/`

### 4. Storage Layer

**Canonical Document Store** - Single source of truth:

```
data/storage/
├── documents/
│   └── {group_guid}/
│       └── {YYYY-MM-DD}/
│           └── {document_guid}.json
├── sources/
│   └── {source_guid}.json
└── groups/
    └── {group_guid}.json
```

**Properties**:
- **Immutable** - Documents never modified (new versions created)
- **Versioned** - New version links to `previous_version_guid`
- **Append-only** - Never delete (only mark as superseded)
- **Group-scoped** - All documents belong to exactly one group
- **Date-partitioned** - Organized by creation date for efficient queries

**Document Schema**:
```json
{
  "guid": "550e8400-...",
  "version": 2,
  "previous_version_guid": "440e8400-...",
  "source_guid": "7c9e6679-...",
  "group": "apac-research",
  "created_at": "2025-12-08T10:30:00Z",
  "language": "en",
  "language_detected": true,
  "title": "Market Analysis Q4 2025",
  "content": "Full text...",
  "word_count": 5432,
  "duplicate_of": null,
  "duplicate_score": 0.0,
  "metadata": {
    "author": "John Smith",
    "region": "APAC",
    "sectors": ["technology"],
    "companies": ["AAPL"],
    "impact_score": 72.5,
    "impact_tier": "GOLD",
    "event_type": "EARNINGS_BEAT"
  }
}
```

### 5. External Services

#### Neo4j Graph Database
- **Port**: 7474 (HTTP), 7687 (Bolt)
- **Purpose**: Entity relationships, graph traversal
- **Storage**: Persistent volume at `data/neo4j/`

#### ChromaDB Vector Database
- **Port**: 8000
- **Purpose**: Semantic similarity search
- **Storage**: Persistent volume at `data/storage/chromadb/`

#### LLM Service (OpenRouter)
- **API**: `https://openrouter.ai/api/v1`
- **Models**: 
  - Chat: `anthropic/claude-opus-4`
  - Embeddings: `qwen/qwen3-embedding-8b`
- **Purpose**: Entity extraction, impact scoring, summarization

---

## Data Flow

### Ingestion Flow

```
Client → Auth → IngestService
                      │
                      ├─→ Validate Source (SourceRegistry)
                      ├─→ Check Word Count (≤ 20K)
                      ├─→ Detect Language (LanguageDetector)
                      ├─→ Check Duplicates (DuplicateDetector)
                      ├─→ Store Document (DocumentStore)
                      ├─→ Extract Entities (LLMService)
                      ├─→ Index Embeddings (EmbeddingIndex → ChromaDB)
                      └─→ Index Graph (GraphIndex → Neo4j)
                      
                   Return: { guid, status, language, extraction }
```

### Query Flow

```
Client → Auth → QueryService
                     │
                     ├─→ Validate Groups
                     ├─→ Semantic Search (EmbeddingIndex → ChromaDB)
                     ├─→ Apply Filters (date, region, sector, etc.)
                     ├─→ Enrich Context (GraphIndex → Neo4j)
                     ├─→ Calculate Scores (semantic + trust + recency + graph)
                     ├─→ Apply Client Ranking (portfolio, watchlist)
                     └─→ Return Ranked Results
                     
                Return: { query, results[], total_found, execution_time_ms }
```

### Client Feed Flow

```
Client → Auth → GraphIndex.get_client_feed()
                     │
                     ├─→ Load Client Profile (Portfolio + Watchlist)
                     ├─→ Traverse Graph (HOLDS → AFFECTED_BY → Documents)
                     ├─→ Calculate Relevance:
                     │    relevance = impact × decay + position_boost + watchlist_boost
                     │    
                     │    Decay by tier:
                     │    • PLATINUM: 0.05/hour
                     │    • GOLD: 0.10/hour
                     │    • SILVER: 0.15/hour
                     │    • BRONZE: 0.20/hour
                     │    • STANDARD: 0.30/hour
                     │
                     ├─→ Apply Group Filter
                     └─→ Return Ranked Feed
                     
                Return: { documents[], relevance_scores[], execution_time_ms }
```

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Language** | Python 3.12+ | Core implementation |
| **Framework** | FastAPI | Web/REST API server |
| **MCP** | fastmcp | Model Context Protocol server |
| **Authentication** | JWT + Vault | Token management |
| **Graph DB** | Neo4j 5.x | Entity relationships |
| **Vector DB** | ChromaDB | Semantic search |
| **LLM** | OpenRouter API | Entity extraction |
| **Storage** | JSON files | Canonical document store |
| **Testing** | pytest | Unit/integration tests |
| **Containerization** | Docker Compose | Service orchestration |

---

## Deployment Architecture

### Docker Compose Stack

```
gofr-net (bridge network)
  ├── gofr-iq-dev (main app)
  ├── gofr-neo4j (graph database)
  ├── gofr-chromadb (vector database)
  └── gofr-vault (auth backend)
```

### Volume Mounts

```
./data/storage      → /app/data/storage      (canonical store)
./data/neo4j        → /var/lib/neo4j/data    (graph persistence)
./data/chromadb     → /chroma/chroma         (vector persistence)
./data/vault        → /vault/data            (auth persistence)
./logs              → /app/logs              (application logs)
```

### Environment Modes

| Mode | Data Dir | Purpose |
|------|----------|---------|
| `PROD` | `./data` | Production deployment |
| `TEST` | `./test/data` | Automated tests |
| `DEV` | `./data` | Local development |

---

## Security Model

### Group-Based Access Control

Every entity (document, source, client) belongs to one or more **groups**:

```
User Token → Groups: ["apac-research", "japan-desk"]
                        │
                        ├─→ Can read documents in those groups
                        ├─→ Can write to groups with `write` scope
                        └─→ Can admin groups with `admin` scope
```

### Scope-Based Permissions

| Scope | Permissions |
|-------|-------------|
| `read` | Query documents, view sources, read client feeds |
| `write` | Ingest documents, update sources |
| `admin` | Manage groups, create tokens, audit logs |

### Authentication Backends

| Backend | Use Case | Configuration |
|---------|----------|---------------|
| **Vault** | Production | `GOFR_AUTH_BACKEND=vault`, requires Vault server |
| **File** | Development | `GOFR_AUTH_BACKEND=file`, stores tokens in JSON |
| **Memory** | Testing | `GOFR_AUTH_BACKEND=memory`, in-memory only |

---

## Performance Characteristics

### Ingestion
- **Throughput**: ~10-20 documents/second (LLM extraction is bottleneck)
- **Latency**: 2-5 seconds per document (includes LLM API call)
- **Concurrency**: Supports parallel ingestion (thread-safe)

### Query
- **Latency**: 100-500ms (semantic search + graph enrichment)
- **Throughput**: ~50-100 queries/second
- **Scaling**: Bottleneck is ChromaDB similarity search

### Storage
- **Growth**: ~10-50KB per document (JSON + metadata)
- **Scale**: Supports millions of documents (file-based partitioning)

---

## Monitoring & Observability

### Audit Logging
All operations logged to `data/storage/audit/{YYYY-MM-DD}/audit.log`:

```json
{
  "timestamp": "2025-12-08T10:30:00Z",
  "operation": "ingest_document",
  "user_token": "user-1234",
  "groups": ["apac-research"],
  "document_guid": "550e8400-...",
  "status": "success"
}
```

### Metrics
- Document ingestion rate
- Query latency percentiles
- LLM API call counts
- Storage growth
- Index rebuild times

### Health Checks
- `/health` endpoint on all servers
- Neo4j connection status
- ChromaDB connection status
- Vault connection status

---

## Future Enhancements

### Phase 1 (Current)
- ✅ File-based canonical storage
- ✅ ChromaDB vector search
- ✅ Neo4j graph index
- ✅ LLM entity extraction
- ✅ Group-based access control

### Phase 2 (Planned)
- [ ] Elasticsearch for metadata/keyword search
- [ ] Redis cache for hot queries
- [ ] Async ingestion queue (Celery/RabbitMQ)
- [ ] Real-time SSE event streams
- [ ] Advanced client personalization

### Phase 3 (Future)
- [ ] Multi-tenancy with isolated data
- [ ] Federated search across groups
- [ ] ML-based impact prediction
- [ ] Automated topic extraction
- [ ] Multi-language cross-search

---

## Related Documentation

- [Authentication Architecture](authentication.md)
- [Graph Design](graph-design.md)
- [Quick Start Guide](../getting-started/quick-start.md)
- [Configuration Reference](../getting-started/configuration.md)
- [Document Ingestion](../features/document-ingestion.md)
- [Hybrid Search](../features/hybrid-search.md)
