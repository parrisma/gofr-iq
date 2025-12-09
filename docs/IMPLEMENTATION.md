# APAC Brokerage News Repository — Implementation Document

**Version:** 1.1  
**Date:** December 8, 2025  
**Project:** gofr-iq  

---

## 1. Overview

This document details the implementation plan for the APAC Brokerage News Repository system within the `gofr-iq` project. The system ingests, stores, and indexes news material from multiple sources with token-based group access control.

### 1.1 Key Design Decisions

| Decision | Resolution |
|----------|------------|
| Document immutability | New versions replace old but remain linked; no hard deletes |
| Document size | Text only, max 20,000 words |
| Duplicate handling | Detected at ingestion; flagged but stored |
| Source access | Full CRUD with group-based permissions |
| Query flow | Similarity first → property filter → group filter |
| Embedding chunking | Configurable chunk size and overlap |
| ChromaDB storage | Default storage, persisted to mounted data volume |
| Group management | Admin interface via storage manager utility script |
| Multi-group queries | Cross-group search within user's permitted groups |
| Language | Auto-detection at ingestion |
| Cross-language search | Enabled via multilingual embeddings |
| Index rebuilding | Incremental rebuild strategy (event-sourced from canonical store) |
| Audit logging | Full trail for all operations (ingest, query, admin) |

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │   MCP       │    │   MCPO      │    │   Web API   │                      │
│  │  (8060)     │    │  (8061)     │    │   (8062)    │                      │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                      │
└─────────┼──────────────────┼──────────────────┼─────────────────────────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AUTH & ACCESS CONTROL                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Token Validation → Group Resolution → Scope Enforcement            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  INGEST SERVICE │  │  QUERY SERVICE  │  │ SOURCE REGISTRY │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CANONICAL DOCUMENT STORE                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  data/documents/{group}/{YYYY-MM-DD}/{GUID}.json                    │    │
│  │  data/sources/{source_guid}.json                                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    Neo4j        │  │   ChromaDB      │  │  Elasticsearch  │
│  (Graph Index)  │  │  (Embeddings)   │  │ (Keyword/Meta)  │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## 3. Component Details

### 3.1 Canonical Document Store

**Location:** `data/documents/` and `data/sources/`

#### 3.1.1 Document Versioning

Documents are **immutable** — updates create new versions linked to the original:

```json
{
  "guid": "550e8400-e29b-41d4-a716-446655440000",
  "version": 2,
  "previous_version_guid": "440e8400-e29b-41d4-a716-446655440000",
  "source_guid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "group": "apac-research",
  "created_at": "2025-12-08T10:30:00Z",
  "language": "en",
  "language_detected": true,
  "title": "Market Analysis Q4 2025 (Updated)",
  "content": "Full text content... (max 20,000 words)",
  "word_count": 5432,
  "duplicate_of": null,
  "duplicate_score": 0.0,
  "metadata": {
    "author": "John Smith",
    "region": "APAC",
    "sectors": ["technology", "finance"],
    "companies": ["AAPL", "GOOGL"],
    "tags": ["quarterly", "analysis"]
  }
}
```

#### 3.1.2 Document Constraints

- **Text only** — no binary attachments
- **Max 20,000 words** — validated at ingestion
- **Language auto-detected** — stored in `language` field with `language_detected: true`

#### 3.1.3 Duplicate Detection

At ingestion, documents are checked for similarity against existing documents in the same group:

- Similarity threshold: configurable (default 0.95)
- If duplicate detected: `duplicate_of` set to original GUID, `duplicate_score` records similarity
- Document still stored (append-only) but flagged

**Source Schema:**

```json
{
  "source_guid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "name": "Reuters APAC",
  "type": "news_agency",
  "region": "APAC",
  "languages": ["en", "zh", "ja"],
  "trust_level": "high",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-12-08T00:00:00Z",
  "access_groups": {
    "read": ["apac-research", "japan-desk", "china-desk"],
    "write": ["apac-research"],
    "admin": ["system-admin"]
  },
  "metadata": {
    "feed_url": "https://...",
    "update_frequency": "realtime"
  }
}
```

**File Path Convention:**

```text
data/
├── documents/
│   └── {group}/
│       └── {YYYY-MM-DD}/
│           └── {guid}.json
├── sources/
│   └── {source_guid}.json
└── chroma/                          # ChromaDB persisted storage
    └── ...
```

### 3.2 Source Registry

**Module:** `app/services/source_registry.py`

Sources have full CRUD with group-based access control:

| Method | Permission | Description |
|--------|------------|-------------|
| `create_source(metadata)` | admin | Register new source, return source_guid |
| `get_source(source_guid)` | read | Retrieve source metadata |
| `list_sources(filters)` | read | List sources with optional filters |
| `update_source(source_guid, metadata)` | write | Update source metadata (audit logged) |
| `delete_source(source_guid)` | admin | Soft-delete source (marks inactive) |

Access is controlled by `access_groups` field on each source.

**Trust Level Scoring:**

Higher trust sources receive a scoring boost in query results:

| Trust Level | Boost Factor |
|-------------|--------------|
| `high` | 1.2x |
| `medium` | 1.0x |
| `low` | 0.8x |
| `unverified` | 0.6x |

### 3.3 Indexing Layer

#### 3.3.1 Neo4j Graph Index

**Module:** `app/services/graph_index.py`

**Node Types:**
- `Source` — News source entity
- `NewsStory` — Document reference (guid, group, created_at)
- `Company` — Company entity (ticker, name, aliases)
- `Sector` — Industry sector
- `Region` — Geographic region

**Relationships:**
- `(NewsStory)-[:PRODUCED_BY]->(Source)`
- `(NewsStory)-[:MENTIONS]->(Company)`
- `(Company)-[:BELONGS_TO]->(Sector)`
- `(Company)-[:OPERATES_IN]->(Region)`
- `(Source)-[:COVERS]->(Region)`

#### 3.3.2 ChromaDB Embeddings

**Module:** `app/services/embedding_index.py`

**Configuration:**

- Collection per group for isolation
- Multilingual embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Metadata: `guid`, `source_guid`, `language`, `created_at`
- **Chunking:** Configurable chunk size and overlap for long documents
- **Storage:** ChromaDB default storage, persisted to `data/chroma/` (mounted volume)

**Chunking Configuration:**

```json
{
  "chunk_size": 1000,
  "chunk_overlap": 200,
  "chunk_strategy": "sentence"
}
```

#### 3.3.3 Elasticsearch Metadata Index

**Module:** `app/services/search_index.py`

**Index per group:** `news-{group}`

**Mappings:**
```json
{
  "mappings": {
    "properties": {
      "guid": { "type": "keyword" },
      "source_guid": { "type": "keyword" },
      "title": { 
        "type": "text",
        "fields": {
          "zh": { "type": "text", "analyzer": "smartcn" },
          "ja": { "type": "text", "analyzer": "kuromoji" },
          "en": { "type": "text", "analyzer": "english" }
        }
      },
      "content": { 
        "type": "text",
        "fields": {
          "zh": { "type": "text", "analyzer": "smartcn" },
          "ja": { "type": "text", "analyzer": "kuromoji" },
          "en": { "type": "text", "analyzer": "english" }
        }
      },
      "language": { "type": "keyword" },
      "region": { "type": "keyword" },
      "sectors": { "type": "keyword" },
      "companies": { "type": "keyword" },
      "created_at": { "type": "date" }
    }
  }
}
```

---

## 4. Services

### 4.1 Ingest Service

**Module:** `app/services/ingest_service.py`

**Ingest Flow:**
```
1. Validate token → extract group
2. Validate payload schema
3. Validate source_guid exists
4. Generate document GUID (UUID v4)
5. Store JSON to canonical path
6. Index in Elasticsearch
7. Generate embedding → store in ChromaDB
8. Create Neo4j nodes and relationships
9. Return { guid, status }
```

**MCP Tool:** `ingest_document`
```python
@mcp.tool()
async def ingest_document(
    title: str,
    content: str,
    source_guid: str,
    language: str,
    metadata: dict
) -> dict:
    """Ingest a news document into the repository."""
```

### 4.2 Query Service

**Module:** `app/services/query_service.py`

**Query Flow (Similarity → Filter → Group):**

```text
1. Validate token → extract user's permitted groups
2. Parse query parameters
3. ChromaDB: Semantic similarity search across user's groups (cross-language enabled)
4. Filter results by metadata properties (date, region, sector, company, language)
5. Apply group filter (ensure results only from permitted groups)
6. Neo4j: Optional graph traversal for related entities
7. Merge and rank results
8. Return documents with scores
```

**MCP Tool:** `query_documents`
```python
@mcp.tool()
async def query_documents(
    query_text: str,
    nearest_k: int = 10,
    filters: dict = None,
    similarity_mode: str = "hybrid",
    scoring_weights: dict = None
) -> dict:
    """Query news documents using hybrid search."""
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query_text` | str | required | Search text |
| `nearest_k` | int | 10 | Number of results |
| `filters.date_from` | str | None | ISO date |
| `filters.date_to` | str | None | ISO date |
| `filters.regions` | list | None | Region filter |
| `filters.sectors` | list | None | Sector filter |
| `filters.companies` | list | None | Company tickers |
| `filters.sources` | list | None | Source GUIDs |
| `filters.languages` | list | None | Language codes |
| `similarity_mode` | str | "hybrid" | "semantic", "keyword", "hybrid" |
| `scoring_weights.semantic` | float | 0.5 | Weight for semantic score |
| `scoring_weights.keyword` | float | 0.3 | Weight for keyword score |
| `scoring_weights.graph` | float | 0.2 | Weight for graph score |

---

## 5. Access Control

### 5.1 Token Structure

Extends `gofr_common.auth` with group claims:
```json
{
  "sub": "user-id",
  "groups": ["apac-research", "japan-desk"],
  "permissions": ["read", "write"],
  "exp": 1733580000
}
```

### 5.2 Group Isolation

**Module:** `app/auth/group_access.py`

- All queries scoped to user's groups
- Ingest requires write permission + group membership
- No cross-group access at API level
- Group enforcement in service layer, not just API

---

## 6. API Interfaces

### 6.1 MCP Server (Port 8060)

**Tools:**
| Tool | Description |
|------|-------------|
| `ingest_document` | Ingest news document |
| `query_documents` | Hybrid search query |
| `get_document` | Retrieve document by GUID |
| `list_sources` | List available sources |
| `get_source` | Get source details |
| `register_source` | Register new source (admin) |

### 6.2 MCPO Server (Port 8061)

OpenAPI-wrapped MCP tools for HTTP access.

### 6.3 Web API (Port 8062)

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/documents` | Ingest document |
| GET | `/api/v1/documents/{guid}` | Get document |
| POST | `/api/v1/search` | Search documents |
| GET | `/api/v1/sources` | List sources |
| GET | `/api/v1/sources/{guid}` | Get source |
| POST | `/api/v1/sources` | Register source |
| GET | `/health` | Health check |

---

## 7. Directory Structure

```
gofr-iq/
├── app/
│   ├── __init__.py
│   ├── config.py                    # Extended config
│   ├── main.py                      # MCP server entry
│   ├── web_main.py                  # Web API entry
│   ├── auth/
│   │   ├── __init__.py
│   │   └── group_access.py          # Group-based access control
│   ├── models/
│   │   ├── __init__.py
│   │   ├── document.py              # Document Pydantic models
│   │   ├── source.py                # Source Pydantic models
│   │   └── query.py                 # Query request/response models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── document_store.py        # Canonical JSON store
│   │   ├── source_registry.py       # Source management
│   │   ├── ingest_service.py        # Ingest orchestration
│   │   ├── query_service.py         # Query orchestration
│   │   ├── graph_index.py           # Neo4j operations
│   │   ├── embedding_index.py       # ChromaDB operations
│   │   └── search_index.py          # Elasticsearch operations
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── ingest_tools.py          # MCP ingest tools
│   │   ├── query_tools.py           # MCP query tools
│   │   └── source_tools.py          # MCP source tools
│   └── web/
│       ├── __init__.py
│       ├── routes.py                # FastAPI routes
│       └── middleware.py            # Auth middleware
├── data/
│   ├── documents/                   # Canonical document store
│   └── sources/                     # Source registry
├── docker/
│   ├── Dockerfile.dev
│   ├── docker-compose.yml           # Neo4j, ChromaDB, Elasticsearch
│   └── ...
├── test/
│   ├── conftest.py
│   ├── test_ingest.py
│   ├── test_query.py
│   ├── test_access_control.py
│   └── ...
└── docs/
    ├── IMPLEMENTATION.md            # This document
    └── plan.md                      # Original requirements
```

---

## 8. Dependencies

**Add to pyproject.toml:**
```toml
dependencies = [
    "neo4j>=5.0.0",
    "chromadb>=0.4.0",
    "elasticsearch>=8.0.0",
    "sentence-transformers>=2.2.0",
]
```

**Docker Services (docker-compose.yml):**
- Neo4j 5.x (port 7687, 7474)
- ChromaDB (port 8000)
- Elasticsearch 8.x (port 9200)

---

## 9. Configuration

**Environment Variables:**
```bash
# Core
GOFR_IQ_MCP_PORT=8060
GOFR_IQ_MCPO_PORT=8061
GOFR_IQ_WEB_PORT=8062

# Data paths
GOFR_IQ_DATA_PATH=/app/data
GOFR_IQ_DOCUMENTS_PATH=/app/data/documents
GOFR_IQ_SOURCES_PATH=/app/data/sources

# Neo4j
GOFR_IQ_NEO4J_URI=bolt://neo4j:7687
GOFR_IQ_NEO4J_USER=neo4j
GOFR_IQ_NEO4J_PASSWORD=secret

# ChromaDB
GOFR_IQ_CHROMA_HOST=chromadb
GOFR_IQ_CHROMA_PORT=8000

# Elasticsearch
GOFR_IQ_ES_HOSTS=http://elasticsearch:9200
GOFR_IQ_ES_USER=elastic
GOFR_IQ_ES_PASSWORD=secret

# Embedding model
GOFR_IQ_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

---

## 10. Phased Build Plan

**Philosophy:** Small incremental steps. Each phase ends with passing tests. Test infrastructure builds out test data store, spins up servers, manages auth.

---

### Test Infrastructure (Built First)

```text
test/
├── conftest.py                      # Fixtures: test data store, auth, servers
├── fixtures/
│   ├── __init__.py
│   ├── data_store.py                # TestDataStore class - creates/cleans test data
│   ├── test_servers.py              # ServerManager - spins up MCP/Web servers
│   └── sample_data.py               # Sample documents, sources, groups
├── data/                            # Runtime test data (gitignored, auto-created)
│   ├── documents/
│   ├── sources/
│   ├── chroma/
│   └── audit/
└── ...test files...
```

**TestDataStore** creates isolated test environment:
- Creates `test/data/` directory structure
- Populates sample sources, documents, groups
- Configures test tokens with group membership
- Cleans up after test session

**ServerManager** handles server lifecycle:
- Starts MCP/MCPO/Web servers pointing to test data
- Uses test JWT secret and token store
- Provides URLs for integration tests
- Auto-stops on fixture teardown

---

### Phase 0: Test Infrastructure Setup
**Goal:** Test harness that creates test data environment and manages servers

| Step | Description | Tests |
|------|-------------|-------|
| 0.1 | Create `test/fixtures/data_store.py` with `TestDataStore` class | `test_data_store_creates_directories` |
| 0.2 | Add sample data generation (3 sources, 10 docs, 2 groups) | `test_sample_data_generation` |
| 0.3 | Create `test/fixtures/test_servers.py` with `ServerManager` | `test_server_manager_import` |
| 0.4 | Update `conftest.py` with fixtures | `test_fixtures_available` |

**Exit Criteria:** `pytest test/test_infrastructure.py` passes

---

### Phase 1: Pydantic Models
**Goal:** Data models for documents, sources, queries

| Step | Description | Tests |
|------|-------------|-------|
| 1.1 | Create `app/models/source.py` - Source model | `test_source_model_valid`, `test_source_model_invalid` |
| 1.2 | Create `app/models/document.py` - Document model with versioning | `test_document_model_valid`, `test_document_versioning` |
| 1.3 | Add word count validation (max 20,000) | `test_document_word_limit` |
| 1.4 | Create `app/models/query.py` - Query request/response | `test_query_request_model`, `test_query_response_model` |

**Exit Criteria:** `pytest test/test_models.py` passes

---

### Phase 2: Canonical Document Store
**Goal:** JSON file storage with GUID naming, group partitioning

| Step | Description | Tests |
|------|-------------|-------|
| 2.1 | Create `app/services/document_store.py` - basic save/load | `test_save_document`, `test_load_document` |
| 2.2 | Add path partitioning: `group/date/guid.json` | `test_document_path_structure` |
| 2.3 | Add document versioning (link to previous) | `test_document_version_chain` |
| 2.4 | Add list documents by group/date | `test_list_documents_by_group` |

**Exit Criteria:** `pytest test/test_document_store.py` passes

---

### Phase 3: Source Registry
**Goal:** CRUD for sources with group-based access

| Step | Description | Tests |
|------|-------------|-------|
| 3.1 | Create `app/services/source_registry.py` - create/get | `test_create_source`, `test_get_source` |
| 3.2 | Add list sources with filters | `test_list_sources`, `test_filter_sources_by_region` |
| 3.3 | Add update source (audit logged) | `test_update_source`, `test_update_creates_audit` |
| 3.4 | Add soft-delete source | `test_soft_delete_source` |
| 3.5 | Add access_groups enforcement | `test_source_access_denied`, `test_source_access_allowed` |

**Exit Criteria:** `pytest test/test_source_registry.py` passes

---

### Phase 4: Group Access Control
**Goal:** Token validation with group claims, scope enforcement

| Step | Description | Tests |
|------|-------------|-------|
| 4.1 | Create `app/auth/group_access.py` - extract groups from token | `test_extract_groups_from_token` |
| 4.2 | Add group membership validation | `test_validate_group_membership` |
| 4.3 | Add permission check (read/write/admin) | `test_permission_check` |
| 4.4 | Integration: document store + group access | `test_document_access_by_group` |

**Exit Criteria:** `pytest test/test_group_access.py` passes

---

### Phase 5: Language Detection
**Goal:** Auto-detect document language at ingestion

| Step | Description | Tests |
|------|-------------|-------|
| 5.1 | Create `app/services/language_detector.py` | `test_detect_english`, `test_detect_chinese`, `test_detect_japanese` |
| 5.2 | Integrate with document ingestion | `test_ingest_auto_detects_language` |

**Exit Criteria:** `pytest test/test_language_detection.py` passes

---

### Phase 6: Duplicate Detection
**Goal:** Flag duplicate documents at ingestion

| Step | Description | Tests |
|------|-------------|-------|
| 6.1 | Create `app/services/duplicate_detector.py` - simple hash | `test_exact_duplicate_detection` |
| 6.2 | Add similarity-based detection (cosine similarity on text) | `test_near_duplicate_detection` |
| 6.3 | Integrate with ingest - set `duplicate_of`, `duplicate_score` | `test_ingest_flags_duplicate` |

**Exit Criteria:** `pytest test/test_duplicate_detection.py` passes

---

### Phase 7: Basic Ingest Service
**Goal:** Orchestrate ingestion without external indexes

| Step | Description | Tests |
|------|-------------|-------|
| 7.1 | Create `app/services/ingest_service.py` - basic flow | `test_ingest_returns_guid` |
| 7.2 | Validate source exists | `test_ingest_rejects_invalid_source` |
| 7.3 | Validate word count | `test_ingest_rejects_long_document` |
| 7.4 | Detect language | `test_ingest_sets_language` |
| 7.5 | Check duplicates | `test_ingest_flags_duplicate` |
| 7.6 | Store to canonical store | `test_ingest_creates_file` |

**Exit Criteria:** `pytest test/test_ingest_service.py` passes

---

### Phase 8: Basic MCP Tools (No External DBs)
**Goal:** MCP server with ingest/retrieve tools using file store only

| Step | Description | Tests |
|------|-------------|-------|
| 8.1 | Create `app/tools/ingest_tools.py` - `ingest_document` | `test_mcp_ingest_tool` |
| 8.2 | Create `app/tools/source_tools.py` - `list_sources`, `get_source` | `test_mcp_source_tools` |
| 8.3 | Create `app/tools/query_tools.py` - `get_document` by GUID | `test_mcp_get_document` |
| 8.4 | Create `app/main.py` - MCP server entry | `test_mcp_server_starts` |
| 8.5 | Integration test with ServerManager | `test_mcp_ingest_end_to_end` |

**Exit Criteria:** `pytest test/test_mcp_tools.py` passes (servers spin up from test fixtures)

---

### Phase 9: Audit Logging
**Goal:** Full audit trail for all operations

| Step | Description | Tests |
|------|-------------|-------|
| 9.1 | Create `app/services/audit_service.py` - log event | `test_audit_log_event` |
| 9.2 | Add audit to ingest | `test_ingest_creates_audit_entry` |
| 9.3 | Add audit to source CRUD | `test_source_crud_audited` |
| 9.4 | Add audit to queries | `test_query_audited` |

**Exit Criteria:** `pytest test/test_audit.py` passes

---

### Phase 10: ChromaDB Integration
**Goal:** Embedding index with configurable chunking

| Step | Description | Tests |
|------|-------------|-------|
| 10.1 | Create `app/services/embedding_index.py` - init ChromaDB | `test_chroma_connection` |
| 10.2 | Add document embedding with chunking | `test_embed_document`, `test_chunking_config` |
| 10.3 | Add similarity search | `test_similarity_search` |
| 10.4 | Test cross-language search | `test_cross_language_similarity` |
| 10.5 | Integrate with ingest service | `test_ingest_creates_embeddings` |

**Exit Criteria:** `pytest test/test_embedding_index.py` passes

---

### Phase 11: Neo4j Integration
**Goal:** Graph index for entity relationships

| Step | Description | Tests |
|------|-------------|-------|
| 11.0 | Create Neo4j Docker container (Dockerfile.neo4j, build/start/stop scripts) | Manual: container runs |
| 11.1 | Create `app/services/graph_index.py` - init Neo4j | `test_neo4j_connection` |
| 11.2 | Create schema (Source, NewsStory, Company, Sector, Region) | `test_neo4j_schema` |
| 11.3 | Add document node creation | `test_create_news_story_node` |
| 11.4 | Add relationships (PRODUCED_BY, MENTIONS) | `test_create_relationships` |
| 11.5 | Add graph traversal queries | `test_graph_traversal` |
| 11.6 | Integrate with ingest service | `test_ingest_creates_graph_nodes` |

**Docker Setup (Step 11.0):**
- `docker/Dockerfile.neo4j` - Neo4j Community Edition with APOC plugins
- `docker/build-neo4j.sh` - Build the Neo4j image
- `docker/start-neo4j.sh` - Start Neo4j with options:
  - `-e` Ephemeral mode (no volume persistence)
  - `-r` Recreate volume (fresh database)
  - `-p PORT` Bolt port (default: 7687 or GOFR_IQ_NEO4J_BOLT_PORT)
  - `-w PORT` HTTP port (default: 7474 or GOFR_IQ_NEO4J_HTTP_PORT)
  - `-n NETWORK` Docker network (default: gofr-net)
- `docker/stop-neo4j.sh` - Stop Neo4j with `-v` to remove volume

**Exit Criteria:** `pytest test/test_graph_index.py` passes

---

### Phase 12: Query Service (Hybrid Search)
**Goal:** Orchestrate similarity → filter → group flow (ChromaDB + Neo4j, no ES)

| Step | Description | Tests |
|------|-------------|-------|
| 12.1 | Create `app/services/query_service.py` - basic structure | `test_query_service_init` |
| 12.2 | Add ChromaDB similarity search | `test_query_similarity` |
| 12.3 | Add in-memory metadata filtering (date, region, sector) | `test_query_with_filters` |
| 12.4 | Add group scoping | `test_query_respects_groups` |
| 12.5 | Add Neo4j graph enrichment | `test_query_with_graph_context` |
| 12.6 | Add trust level scoring boost | `test_trust_level_scoring` |
| 12.7 | MCP tool: `query_documents` | `test_mcp_query_documents` |

**Exit Criteria:** `pytest test/test_query_service.py` passes

---

### Phase 13: Web API
**Goal:** FastAPI endpoints for non-MCP access

| Step | Description | Tests |
|------|-------------|-------|
| 13.1 | Create `app/web/routes.py` - health endpoint | `test_web_health` |
| 13.2 | Add POST `/api/v1/documents` | `test_web_ingest` |
| 13.3 | Add GET `/api/v1/documents/{guid}` | `test_web_get_document` |
| 13.4 | Add POST `/api/v1/search` | `test_web_search` |
| 13.5 | Add source endpoints | `test_web_source_crud` |
| 13.6 | Add auth middleware | `test_web_auth_required` |
| 13.7 | Create `app/web_main.py` entry | `test_web_server_starts` |

**Exit Criteria:** `pytest test/test_web_api.py` passes

---

### Phase 14: Index Rebuild & Admin Tools
**Goal:** Incremental rebuild, admin CLI

| Step | Description | Tests |
|------|-------------|-------|
| 14.1 | Create `app/services/index_manager.py` - scan unindexed | `test_find_unindexed_documents` |
| 14.2 | Add incremental rebuild | `test_incremental_rebuild` |
| 14.3 | Add full rebuild | `test_full_rebuild` |
| 14.4 | Add verify mode | `test_verify_indexes` |
| 14.5 | Create `scripts/storage_manager.sh` | `test_storage_manager_help` |
| 14.6 | MCP tool: `rebuild_index` (admin) | `test_mcp_rebuild_index` |

**Exit Criteria:** `pytest test/test_index_manager.py` passes

---

### Phase 15: Docker & Integration
**Goal:** Full stack in containers (without Elasticsearch)

| Step | Description | Tests |
|------|-------------|-------|
| 15.1 | Create `docker/docker-compose.yml` (ChromaDB, Neo4j) | Manual: `docker-compose up` |
| 15.2 | Update Dockerfile.dev for all deps | Manual: container builds |
| 15.3 | Full integration test suite | `test_integration_full_flow` |
| 15.4 | Performance test (1000 docs) | `test_performance_ingest_1000` |

**Exit Criteria:** `pytest test/test_integration.py` passes in container

---

### Phase 16 (OPTIONAL): Elasticsearch Integration
**Goal:** Add keyword search with multilingual analyzers for enhanced filtering

*This phase is optional. The system is fully functional with ChromaDB + Neo4j.*

| Step | Description | Tests |
|------|-------------|-------|
| 16.1 | Create `app/services/search_index.py` - init ES client | `test_es_connection` |
| 16.2 | Create index with multilingual mappings | `test_es_index_creation` |
| 16.3 | Add document indexing | `test_es_index_document` |
| 16.4 | Add keyword search | `test_es_keyword_search` |
| 16.5 | Add metadata filters | `test_es_filter_by_date`, `test_es_filter_by_region` |
| 16.6 | Integrate with ingest service | `test_ingest_indexes_in_es` |
| 16.7 | Update query service to use ES for filtering | `test_query_with_es_filters` |
| 16.8 | Update docker-compose.yml to include ES | Manual: ES container runs |

**Exit Criteria:** `pytest test/test_search_index.py` passes

**Benefits of adding Elasticsearch:**
- Faster metadata filtering at scale (vs in-memory)
- Full-text keyword search with language-specific analyzers
- Faceted search and aggregations
- Synonym support

---

### Summary: Test Count by Phase

| Phase | Tests | Cumulative |
|-------|-------|------------|
| 0 - Test Infrastructure | 4 | 4 |
| 1 - Models | 6 | 10 |
| 2 - Document Store | 4 | 14 |
| 3 - Source Registry | 7 | 21 |
| 4 - Group Access | 4 | 25 |
| 5 - Language Detection | 4 | 29 |
| 6 - Duplicate Detection | 3 | 32 |
| 7 - Ingest Service | 6 | 38 |
| 8 - MCP Tools | 5 | 43 |
| 9 - Audit | 4 | 47 |
| 10 - ChromaDB | 5 | 52 |
| 11 - Neo4j | 6 | 58 |
| 12 - Query Service | 7 | 65 |
| 13 - Web API | 7 | 72 |
| 14 - Index Rebuild | 6 | 78 |
| 15 - Integration | 4 | 82 |
| **16 - Elasticsearch (Optional)** | 8 | 90 |

**Core system complete at Phase 15 with 82 tests.**

---

## 11. Open Questions

~~All questions resolved — see Section 1.1 Key Design Decisions.~~

---

## 12. Audit Logging

**Module:** `app/services/audit_service.py`

Full audit trail for all operations:

| Event Type | Data Captured |
|------------|---------------|
| `document.ingest` | guid, source_guid, group, user, timestamp, duplicate_status |
| `document.query` | query_text, filters, user, groups, timestamp, result_count |
| `document.retrieve` | guid, user, group, timestamp |
| `source.create` | source_guid, user, timestamp |
| `source.update` | source_guid, user, changes, timestamp |
| `source.delete` | source_guid, user, timestamp |
| `admin.rebuild` | index_type, user, timestamp, status |
| `admin.group_change` | group, action, user, timestamp |

**Storage:** `data/audit/{YYYY-MM-DD}/audit.jsonl` (append-only JSONL)

---

## 13. Index Rebuild Strategy

**Module:** `app/services/index_manager.py`

**Incremental Rebuild (Event-Sourced):**

Rather than periodic full rebuilds, indexes are rebuilt incrementally by replaying events from the canonical store:

```text
1. Scan canonical document store for documents not in index
   - Compare document GUIDs against index metadata
   - Track last-indexed timestamp per group

2. For each missing/outdated document:
   - Read JSON from canonical store
   - Generate embedding (if ChromaDB)
   - Create index entry (ES/Neo4j/Chroma)
   - Update tracking metadata

3. Handle deletions (soft-delete flags):
   - Mark documents as inactive in indexes
   - Do not remove from canonical store
```

**Rebuild Triggers:**

- **Automatic:** Background worker checks for unindexed documents every N minutes
- **Manual:** Admin tool `scripts/storage_manager.sh rebuild [--index=all|chroma|elastic|neo4j]`
- **On-Demand:** MCP tool `rebuild_index` for admin users

**Recovery Modes:**

| Mode | Description |
|------|-------------|
| `incremental` | Only index documents not yet indexed (default) |
| `full` | Rebuild entire index from canonical store |
| `verify` | Compare indexes against canonical store, report discrepancies |

---

## 14. Admin Utility Script

**Location:** `scripts/storage_manager.sh`

```bash
# Group management
./storage_manager.sh group list
./storage_manager.sh group create <name>
./storage_manager.sh group delete <name>
./storage_manager.sh group add-user <group> <user>

# Index management  
./storage_manager.sh rebuild --index=all
./storage_manager.sh rebuild --index=chroma --group=apac-research
./storage_manager.sh verify --index=all
./storage_manager.sh stats

# Audit
./storage_manager.sh audit search --user=<user> --from=<date> --to=<date>
./storage_manager.sh audit export --format=json --output=audit.json

# Maintenance
./storage_manager.sh vacuum --dry-run
./storage_manager.sh backup --output=/backups/
```

---

**Document updated:** December 8, 2025
