# APAC Brokerage News Repository — Implementation Document

**Version:** 2.0  
**Date:** December 8, 2025  
**Project:** gofr-iq  

---

## 1. Overview

This document details the implementation plan for the APAC Brokerage News Repository system within the `gofr-iq` project. The system ingests, stores, and indexes news material from multiple sources for institutional brokerage clients (long-only funds). **No client profiling is performed** — the system only holds and indexes material.

### 1.1 Key Design Decisions

| Decision | Resolution |
|----------|------------|
| Document ownership | Each document belongs to exactly ONE group (by group GUID) |
| Source ownership | Each source belongs to exactly ONE group (by group GUID) |
| Group identity | Groups are identified by GUID, not name |
| Access control | JWT tokens grant CRUD permissions on groups; no user identity concept |
| EventType structure | Separate nodes in Neo4j with controlled vocabulary (EARNINGS, M&A, REGULATORY, MACRO, CRISIS, LEADERSHIP, PRODUCT, LEGAL, ESG, CAPITAL) |
| Tag structure | Separate nodes in Neo4j with flexible organic taxonomy |
| ImpactScore | Property on document with target distribution (critical 0.5%, high 2%, medium 7%, low 20%, minimal 70.5%) |
| HorizonTime | Absolute datetime property on document (ISO 8601 format) |
| LLM-powered ingestion | All entity extraction happens at ingest time via LLM (EventTypes, Tags, Companies, ImpactScore, HorizonTime) |
| Client types | Not in data model; used for design validation (backtest that queries serve all fund types) |
| Token management | Tokens created via token_manager.sh, associated with groups |
| Document immutability | New versions replace old but remain linked; no hard deletes |
| Document size | Text only, max 20,000 words |
| Duplicate handling | Detected at ingestion; flagged but stored |
| Source access | Full CRUD within owning group based on token permissions |
| Query flow | Elastic filter → ChromaDB similarity → Neo4j traversal |
| Embedding chunking | Configurable chunk size and overlap |
| ChromaDB storage | Default storage, persisted to mounted data volume |
| Group management | Admin interface via storage manager utility script |
| Multi-group queries | Cross-group search within token's permitted groups |
| Language | Auto-detection at ingestion (Chinese, Japanese, English) |
| Cross-language search | Enabled via multilingual embeddings |
| Index rebuilding | Incremental rebuild strategy (event-sourced from canonical store) |
| Audit logging | Full trail for all operations (ingest, query, admin) |
| **LLM-powered ingestion** | LLM extracts entities, classifications, and relationships from raw text |
| **Impact scoring** | Absolute relevance classification assigned at ingestion |
| **Horizon time** | Temporal relevance window for each story |
| **No client profiling** | System holds/indexes material only; no directional advice |
| **Company aliases** | Companies have multiple identifiers (tickers, names) resolved to canonical entity |
| **Recency boost** | Recent news scores higher; decays over time |
| **Horizon relevance** | News approaching/within horizon window boosted; expired news penalized |

### 1.2 Target Client Types (Design Validation)

The system is designed to serve institutional long-only funds. These client types inform the graph structure and query patterns but are **not modeled as entities**:

| Client Type | Focus Areas |
|-------------|-------------|
| Global Equity Fund | Broad market coverage, cross-region stories |
| Regional Equity Fund | Region-specific news, local regulatory |
| Sector-Focused Fund | Deep sector coverage, competitive dynamics |
| Thematic / ESG Fund | ESG tags, sustainability, governance events |
| Dividend / Income Fund | Earnings, dividend announcements, yield-relevant |
| Growth Fund | M&A, expansion, innovation, new products |
| Value Fund | Restructuring, undervaluation signals, turnarounds |
| Pension / Sovereign Wealth | Macro events, regulatory, long-horizon stories |
| Index-Tracking / Passive | Index rebalancing, constituent changes |
| Balanced / Multi-Asset | Cross-asset impact, macro themes |

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
  "group_guid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "created_at": "2025-12-08T10:30:00Z",
  "language": "en",
  "language_detected": true,
  "title": "Apple Announces Major Acquisition of AI Startup",
  "content": "Full text content... (max 20,000 words)",
  "word_count": 1523,
  "duplicate_of": null,
  "duplicate_score": 0.0,
  
  "impact_score": "high",
  "horizon_time": "2025-12-15T00:00:00Z",
  
  "extracted": {
    "event_types": ["M&A", "AI"],
    "tags": ["AI", "tech-acquisition", "growth"],
    "companies": [
      {"ticker": "AAPL", "name": "Apple Inc", "relevance": 0.95},
      {"ticker": "GOOGL", "name": "Alphabet", "relevance": 0.3}
    ],
    "sectors": ["technology", "artificial-intelligence"],
    "regions": ["north-america"]
  },
  
  "metadata": {
    "author": "John Smith",
    "original_url": "https://...",
    "published_at": "2025-12-08T09:00:00Z"
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
  "group_guid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Reuters APAC",
  "type": "news_agency",
  "region": "APAC",
  "languages": ["en", "zh", "ja"],
  "trust_level": "high",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-12-08T00:00:00Z",
  "active": true,
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
│   └── {group_guid}/
│       └── {YYYY-MM-DD}/
│           └── {guid}.json
├── sources/
│   └── {group_guid}/
│       └── {source_guid}.json
├── groups/
│   └── {group_guid}.json            # Group metadata and user permissions
└── chroma/                          # ChromaDB persisted storage
    └── ...
```

### 3.2 Source Registry

**Module:** `app/services/source_registry.py`

Each source belongs to exactly ONE group. Tokens with appropriate permissions on that group can perform CRUD:

| Method | Permission | Description |
|--------|------------|-------------|
| `create_source(group_guid, metadata)` | create | Register new source in group, return source_guid |
| `get_source(source_guid)` | read | Retrieve source metadata (requires group read) |
| `list_sources(group_guid, filters)` | read | List sources in group with optional filters |
| `update_source(source_guid, metadata)` | update | Update source metadata (audit logged) |
| `delete_source(source_guid)` | delete | Soft-delete source (marks `active: false`) |

Access is controlled by the token's permissions on the source's `group_guid`.

### 3.3 Group Registry

**Module:** `app/services/group_registry.py`

**Location:** `data/groups/{group_guid}.json`

Groups define isolation boundaries and token permissions:

**Group Schema:**

```json
{
  "group_guid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "APAC Research",
  "description": "Asia-Pacific research team documents",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-12-08T00:00:00Z",
  "active": true,
  "tokens": {
    "token_id_001": ["create", "read", "update", "delete"],
    "token_id_002": ["read"],
    "token_id_003": ["create", "read", "update"]
  },
  "metadata": {
    "region": "APAC",
    "department": "Research"
  }
}
```

**Token Permissions (per group):**

| Permission | Allows |
|------------|--------|
| `create` | Ingest documents, register sources |
| `read` | Query documents, view sources |
| `update` | Update document metadata, update sources |
| `delete` | Soft-delete documents and sources |

A single JWT token may have access to multiple groups with different permission sets in each. Tokens are created via `token_manager.sh` and distributed to users/systems.

**Trust Level Scoring:**

Higher trust sources receive a scoring boost in query results:

| Trust Level | Boost Factor |
|-------------|--------------|
| `high` | 1.2x |
| `medium` | 1.0x |
| `low` | 0.8x |
| `unverified` | 0.6x |

**Recency Boost:**

Recent news is more valuable. Score decays over time:

| Age | Recency Factor |
|-----|----------------|
| < 1 hour | 1.5x |
| 1-6 hours | 1.3x |
| 6-24 hours | 1.2x |
| 1-3 days | 1.0x |
| 3-7 days | 0.9x |
| 1-2 weeks | 0.7x |
| 2-4 weeks | 0.5x |
| > 1 month | 0.3x |

**Horizon Time Relevance:**

News is most valuable when its `horizon_time` is approaching or current:

| Horizon Status | Horizon Factor |
|----------------|----------------|
| Horizon in next 24 hours | 1.5x (urgent) |
| Horizon in 1-7 days | 1.3x (imminent) |
| Horizon in 1-4 weeks | 1.1x (upcoming) |
| Horizon in 1-3 months | 1.0x (forward) |
| Horizon > 3 months out | 0.9x (distant) |
| **Horizon passed < 1 week ago** | 0.5x (recent past) |
| **Horizon passed > 1 week ago** | 0.2x (expired) |
| No horizon (null) | 1.0x (timeless) |

**Combined Scoring Formula:**

```
final_score = base_similarity_score 
            × trust_factor 
            × recency_factor 
            × horizon_factor
```

### 3.4 ImpactScore Distribution

The `impact_score` field categorizes news by expected market impact. Target distribution ensures proper calibration:

| Score | Target % | Description | Examples |
|-------|----------|-------------|----------|
| `critical` | 0.5% | Major market-moving events | Systemic risk, major regulatory changes, large M&A |
| `high` | 2% | Significant impact on sector/company | Earnings surprises, management changes, material events |
| `medium` | 7% | Moderate relevance | Analyst upgrades, operational updates |
| `low` | 20% | Minor relevance | Routine announcements, minor news |
| `minimal` | 70.5% | Background/noise | General market commentary, peripheral mentions |

The LLM is prompted with this target distribution to maintain calibration. Monthly audits verify actual vs. target distribution.

### 3.5 HorizonTime

The `horizon_time` field indicates when the news event's impact is expected to manifest:

- **Format:** ISO 8601 absolute datetime (e.g., `2025-12-15T00:00:00Z`)
- **Usage:** Filters for "news relevant in next 30 days" or "events impacting Q1 2026"
- **Examples:**
  - Earnings announcement: Date of earnings release
  - M&A deal: Expected closing date
  - Regulatory change: Effective date of new regulation
  - IPO: Expected listing date
- **Null:** Allowed when no specific future date is identifiable (immediate/ongoing impact)

### 3.6 Indexing Layer

#### 3.6.1 Neo4j Graph Index

**Module:** `app/services/graph_index.py`

**Node Types:**

*Core Nodes:*
- `Group` — Group entity (group_guid, name)
- `Source` — News source entity (linked to Group)
- `NewsStory` — Document reference (guid, group_guid, created_at, impact_score, horizon_time)

*Entity Nodes:*
- `Company` — Company entity (ticker, name, aliases, exchange)
- `Sector` — Industry sector (code, name)
- `Region` — Geographic region (code, name)

**Company Node Schema:**

```json
{
  "ticker": "TSM",
  "name": "Taiwan Semiconductor Manufacturing",
  "aliases": [
    {"type": "ticker", "value": "2330.TW", "exchange": "TWSE"},
    {"type": "ticker", "value": "TSM", "exchange": "NYSE"},
    {"type": "name", "value": "TSMC"},
    {"type": "name", "value": "台積電"},
    {"type": "name", "value": "台湾セミコンダクター"}
  ],
  "primary_exchange": "TWSE",
  "isin": "TW0002330008"
}
```

**Alias Resolution:** When querying by company, the system:
1. Searches all alias values (case-insensitive)
2. Resolves to canonical Company node
3. Returns all news mentioning that company regardless of which alias was used in the source

*Classification Nodes:*
- `EventType` — Controlled vocabulary of event classifications
- `Tag` — Flexible tagging taxonomy

**EventType Nodes (Controlled Vocabulary):**

| EventType | Description |
|-----------|-------------|
| `EARNINGS` | Earnings releases, guidance, financial results |
| `M&A` | Mergers, acquisitions, divestitures |
| `REGULATORY` | Regulatory actions, compliance, government policy |
| `MACRO` | Macroeconomic events, central bank actions, trade policy |
| `CRISIS` | Risk events, scandals, operational failures |
| `LEADERSHIP` | Management changes, board appointments |
| `PRODUCT` | Product launches, R&D announcements |
| `LEGAL` | Litigation, settlements, legal disputes |
| `ESG` | Environmental, social, governance events |
| `CAPITAL` | Dividends, buybacks, capital allocation |

**Tag Nodes (Flexible Taxonomy):**

Tags are more granular than EventTypes and can be added organically:
- `AI`, `ESG`, `IPO`, `tech-acquisition`, `quarterly`, `guidance-raised`, `guidance-lowered`
- `china-exposure`, `rate-sensitive`, `commodity-linked`, `dividend-growth`
- Tags are lowercase with hyphens, created on first use

**Relationships:**

*Ownership/Source:*
- `(NewsStory)-[:BELONGS_TO]->(Group)`
- `(NewsStory)-[:PRODUCED_BY]->(Source)`
- `(Source)-[:BELONGS_TO]->(Group)`

*Entity Mentions:*
- `(NewsStory)-[:MENTIONS {relevance: float}]->(Company)`
- `(NewsStory)-[:COVERS_SECTOR]->(Sector)`
- `(NewsStory)-[:COVERS_REGION]->(Region)`

*Classification:*
- `(NewsStory)-[:CLASSIFIED_AS]->(EventType)`
- `(NewsStory)-[:TAGGED_WITH]->(Tag)`

*Entity Taxonomy:*
- `(Company)-[:IN_SECTOR]->(Sector)`
- `(Company)-[:OPERATES_IN]->(Region)`
- `(Source)-[:COVERS]->(Region)`

*Inter-Entity:*
- `(Company)-[:RELATES_TO {relationship_type: str}]->(Company)` — Supplier, competitor, subsidiary
- `(EventType)-[:OFTEN_TAGGED_WITH]->(Tag)` — Common co-occurrences

#### 3.6.2 ChromaDB Embeddings

**Module:** `app/services/embedding_index.py`

**Configuration:**

- Collection per group_guid for isolation
- Multilingual embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Metadata: `guid`, `group_guid`, `source_guid`, `language`, `created_at`
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

#### 3.6.3 Elasticsearch Metadata Index

**Module:** `app/services/search_index.py`

**Index per group:** `news-{group_guid}`

**Mappings:**
```json
{
  "mappings": {
    "properties": {
      "guid": { "type": "keyword" },
      "group_guid": { "type": "keyword" },
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

## 4. LLM-Powered Ingestion Pipeline

At ingestion time, raw news content is processed by an LLM to extract structured metadata. This is a **core architectural decision** — all classification happens at write time, not query time.

### 4.1 Extraction Flow

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RAW STORY INPUT                                   │
│  { title, content, source_guid, group_guid, metadata }                      │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LLM EXTRACTION SERVICE                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Input: title + content (full text, max 20K words)                  │    │
│  │  Model: Configurable (Claude, GPT-4, local model)                   │    │
│  │  Prompt: Structured extraction with target distributions            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXTRACTED FIELDS                                    │
│  {                                                                          │
│    "event_types": ["M&A", "AI"],        // From controlled vocabulary       │
│    "tags": ["tech-acquisition", "AI"],   // Flexible taxonomy               │
│    "impact_score": "high",               // With target distribution        │
│    "horizon_time": "2025-03-15T00:00:00Z", // Expected impact date          │
│    "companies": [                                                           │
│      {"ticker": "AAPL", "name": "Apple", "relevance": 0.95}                 │
│    ],                                                                       │
│    "sectors": ["technology", "AI"],                                         │
│    "regions": ["north-america"]                                             │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 LLM Extraction Service

**Module:** `app/services/llm_extraction.py`

**Configuration:**

```python
LLM_CONFIG = {
    "provider": "anthropic",  # or "openai", "local"
    "model": "claude-sonnet-4-20250514",
    "temperature": 0.1,  # Low for consistent extraction
    "max_tokens": 2000,
    "retry_attempts": 3,
    "fallback_provider": "openai"  # Fallback if primary fails
}
```

**Prompt Structure:**

```text
You are an expert financial news analyst extracting structured metadata 
from news articles for an institutional investment research platform.

TARGET DISTRIBUTIONS (maintain these ratios):
- impact_score: critical (0.5%), high (2%), medium (7%), low (20%), minimal (70.5%)

CONTROLLED VOCABULARY for event_types:
- EARNINGS, M&A, REGULATORY, MACRO, CRISIS, LEADERSHIP, PRODUCT, LEGAL, ESG, CAPITAL

Extract the following from the article:

1. EVENT_TYPES: Select 1-3 from controlled vocabulary
2. TAGS: Add 2-5 granular tags (lowercase-with-hyphens)
3. IMPACT_SCORE: One of critical/high/medium/low/minimal
4. HORIZON_TIME: ISO date when impact expected (or null)
5. COMPANIES: List with ticker, name, relevance (0.0-1.0)
6. SECTORS: List of relevant sectors
7. REGIONS: List of relevant geographic regions

<article>
{title}

{content}
</article>

Respond in JSON format only.
```

### 4.3 Extraction Validation

Extracted fields are validated before storage:

| Field | Validation |
|-------|------------|
| `event_types` | Must be from controlled vocabulary, 1-3 items |
| `tags` | Lowercase with hyphens, 2-10 items |
| `impact_score` | Must be one of: critical, high, medium, low, minimal |
| `horizon_time` | Valid ISO 8601 datetime or null |
| `companies` | Ticker must be uppercase, relevance 0.0-1.0 |
| `sectors` | From predefined sector list |
| `regions` | From predefined region list |

**Fallback Behavior:**

If LLM extraction fails after retries:
1. Document is stored with empty `extracted` fields
2. Flagged for manual review (`extraction_status: "failed"`)
3. Alert logged for operations

---

## 5. Services

### 5.1 Ingest Service

**Module:** `app/services/ingest_service.py`

**Ingest Flow:**
```
1. Validate token → extract token_id and permitted group_guids
2. Validate token has 'create' permission on target group_guid
3. Validate payload schema (title, content, source_guid)
4. Validate source_guid exists and belongs to same group
5. Generate document GUID (UUID v4)
6. Detect language (auto-detect from content)
7. Check for duplicates (similarity against existing docs in group)
8. **LLM Extraction** → extract event_types, tags, impact_score, horizon_time, companies, sectors, regions
9. Store JSON to canonical path: data/documents/{group_guid}/{date}/{guid}.json
10. Index in Elasticsearch (if enabled) - include extracted metadata
11. Generate embedding → store in ChromaDB
12. Create Neo4j nodes and relationships (including EventType, Tag nodes)
13. Log audit event
11. Return { guid, status }
```

**MCP Tool:** `ingest_document`
```python
@mcp.tool()
async def ingest_document(
    group_guid: str,
    title: str,
    content: str,
    source_guid: str,
    metadata: dict
) -> dict:
    """Ingest a news document into the repository."""
```

### 4.2 Query Service

**Module:** `app/services/query_service.py`

**Query Flow (Similarity → Filter → Score → Rank):**

```text
1. Validate token → extract token_id and permitted group_guids with 'read' permission
2. Parse query parameters
3. Resolve company aliases → canonical Company nodes
4. Optionally filter to specific group_guids (must be subset of permitted)
5. ChromaDB: Semantic similarity search across permitted groups (cross-language enabled)
6. Filter results by metadata properties (date, region, sector, company, language)
7. Neo4j: Optional graph traversal for related entities
8. Apply scoring boosts:
   a. Trust level boost (source credibility)
   b. Recency boost (time since created_at)
   c. Horizon relevance boost (time to/since horizon_time)
9. Calculate final_score = similarity × trust × recency × horizon
10. Rank and merge results
11. Log audit event
12. Return documents with scores and score breakdown
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
| `group_guids` | list | None | Limit to specific groups (must have read access) |
| `nearest_k` | int | 10 | Number of results |
| `filters.date_from` | str | None | ISO date for created_at |
| `filters.date_to` | str | None | ISO date for created_at |
| `filters.horizon_from` | str | None | ISO date - events impacting after this date |
| `filters.horizon_to` | str | None | ISO date - events impacting before this date |
| `filters.impact_scores` | list | None | Filter by impact: ["critical", "high"] |
| `filters.event_types` | list | None | Filter by EventType: ["EARNINGS", "M&A"] |
| `filters.tags` | list | None | Filter by tags: ["AI", "ESG"] |
| `filters.regions` | list | None | Region filter |
| `filters.sectors` | list | None | Sector filter |
| `filters.companies` | list | None | Company tickers |
| `filters.sources` | list | None | Source GUIDs |
| `filters.languages` | list | None | Language codes |
| `similarity_mode` | str | "hybrid" | "semantic", "keyword", "hybrid" |
| `scoring_weights.semantic` | float | 0.5 | Weight for semantic score |
| `scoring_weights.keyword` | float | 0.3 | Weight for keyword score |
| `scoring_weights.graph` | float | 0.2 | Weight for graph score |
| `scoring_boosts.recency` | bool | true | Apply recency decay boost |
| `scoring_boosts.horizon` | bool | true | Apply horizon relevance boost |
| `scoring_boosts.trust` | bool | true | Apply source trust level boost |
| `include_expired` | bool | false | Include news with passed horizon_time |

**Filter Examples:**

```python
# High-impact earnings news in next 30 days
filters = {
    "event_types": ["EARNINGS"],
    "impact_scores": ["critical", "high"],
    "horizon_from": "2025-12-08",
    "horizon_to": "2026-01-08"
}

# ESG-related news about specific companies
filters = {
    "event_types": ["ESG"],
    "companies": ["AAPL", "MSFT", "GOOGL"],
    "tags": ["climate", "carbon"]
}

# M&A activity in technology sector
filters = {
    "event_types": ["M&A"],
    "sectors": ["technology"],
    "impact_scores": ["critical", "high", "medium"]
}
```

---

## 6. Access Control

### 6.1 Token Structure

Extends `gofr_common.auth`. JWT tokens are created with a unique `jti` (token ID) that maps to group permissions:

```json
{
  "jti": "token_id_001",
  "group": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "aud": "gofr-iq-api",
  "iat": 1733580000,
  "exp": 1736172000
}
```

At request time, the system:
1. Validates the JWT token
2. Extracts `jti` (token ID) from token
3. Queries group registry for all groups containing this token ID
4. Returns token's permissions per group

**Token Creation:**
```bash
# Create token with access to a group
./scripts/token_manager.sh create --group=<group_guid> --permissions=create,read,update,delete

# Add existing token to another group
./scripts/token_manager.sh add-to-group --token-id=<token_id> --group=<group_guid> --permissions=read
```

### 6.2 Group Isolation

**Module:** `app/auth/group_access.py`

- Documents and sources belong to exactly ONE group
- Tokens may have access to multiple groups with different permissions per group
- All queries automatically scoped to token's permitted groups (with 'read' permission)
- Ingest requires 'create' permission on target group
- Update requires 'update' permission on document's group
- No cross-group access — a document in group A cannot be seen by tokens without 'read' on group A
- Group enforcement in service layer, not just API

---

## 7. Client Type Validation

The system is designed to serve institutional asset managers with diverse investment mandates. While client profiling is NOT part of the data model, the design is validated against these client archetypes to ensure query flexibility.

### 7.1 Client Archetypes

| Client Type | Primary Queries | Key Filters |
|-------------|-----------------|-------------|
| **Global Equity Funds** | Company mentions across all regions | `companies`, `sectors`, `impact_scores: [critical, high]` |
| **Regional Funds (APAC)** | Regional news, local regulatory | `regions: [asia-pacific, china, japan]`, `event_types: [REGULATORY, MACRO]` |
| **Sector Specialists** | Sector-specific news, competitors | `sectors: [technology]`, `event_types: [PRODUCT, M&A]` |
| **Thematic/ESG Funds** | ESG events, sustainability | `event_types: [ESG]`, `tags: [climate, governance, diversity]` |
| **Dividend/Income Funds** | Dividend announcements, capital returns | `event_types: [CAPITAL]`, `tags: [dividend, buyback]` |
| **Growth Funds** | M&A, product launches, expansion | `event_types: [M&A, PRODUCT]`, `impact_scores: [critical, high]` |
| **Value Funds** | Restructuring, turnaround situations | `event_types: [LEADERSHIP, CRISIS]`, `tags: [restructuring, turnaround]` |
| **Pension/Sovereign Funds** | Long-horizon macro events | `horizon_from: [+1 year]`, `event_types: [REGULATORY, MACRO]` |
| **Index Trackers** | Major index-moving events | `impact_scores: [critical]`, broad company coverage |
| **Balanced/Multi-Asset** | Cross-asset macro themes | `event_types: [MACRO]`, `sectors` across asset classes |

### 7.2 Design Validation Checklist

| Requirement | How Addressed |
|-------------|---------------|
| Filter by event significance | `impact_score` with calibrated distribution |
| Filter by time horizon | `horizon_time` with range queries |
| Filter by event category | `event_types` controlled vocabulary |
| Flexible thematic filtering | `tags` with organic taxonomy |
| Company relationship queries | Neo4j RELATES_TO relationships |
| Cross-language search | Multilingual embeddings in ChromaDB |
| Regional focus | `regions` filter and neo4j COVERS relationship |

---

## 8. API Interfaces

### 8.1 MCP Server (Port 8060)

**Tools:**
| Tool | Description |
|------|-------------|
| `ingest_document` | Ingest news document into a group |
| `query_documents` | Hybrid search query across permitted groups |
| `get_document` | Retrieve document by GUID |
| `list_sources` | List sources in permitted groups |
| `get_source` | Get source details |
| `register_source` | Register new source (requires 'create' on group) |
| `list_groups` | List token's permitted groups |
| `get_group` | Get group details |

### 8.2 MCPO Server (Port 8061)

OpenAPI-wrapped MCP tools for HTTP access.

### 8.3 Web API (Port 8062)

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/documents` | Ingest document |
| GET | `/api/v1/documents/{guid}` | Get document |
| POST | `/api/v1/search` | Search documents |
| GET | `/api/v1/sources` | List sources |
| GET | `/api/v1/sources/{guid}` | Get source |
| POST | `/api/v1/sources` | Register source |
| GET | `/api/v1/groups` | List token's groups |
| GET | `/api/v1/groups/{guid}` | Get group details |
| GET | `/health` | Health check |

---

## 9. Directory Structure

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
│   │   ├── event_type.py            # EventType controlled vocabulary
│   │   ├── tag.py                   # Tag taxonomy models
│   │   └── query.py                 # Query request/response models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── document_store.py        # Canonical JSON store
│   │   ├── source_registry.py       # Source management
│   │   ├── group_registry.py        # Group management
│   │   ├── llm_extraction.py        # LLM-powered entity extraction
│   │   ├── ingest_service.py        # Ingest orchestration
│   │   ├── query_service.py         # Query orchestration
│   │   ├── graph_index.py           # Neo4j operations
│   │   ├── embedding_index.py       # ChromaDB operations
│   │   └── search_index.py          # Elasticsearch operations
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── ingest_tools.py          # MCP ingest tools
│   │   ├── query_tools.py           # MCP query tools
│   │   ├── source_tools.py          # MCP source tools
│   │   └── group_tools.py           # MCP group tools
│   └── web/
│       ├── __init__.py
│       ├── routes.py                # FastAPI routes
│       └── middleware.py            # Auth middleware
├── data/
│   ├── documents/                   # Canonical document store (by group_guid)
│   ├── sources/                     # Source registry (by group_guid)
│   └── groups/                      # Group registry
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

## 10. Dependencies

**Add to pyproject.toml:**
```toml
dependencies = [
    "neo4j>=5.0.0",
    "chromadb>=0.4.0",
    "elasticsearch>=8.0.0",
    "sentence-transformers>=2.2.0",
    "anthropic>=0.18.0",
    "openai>=1.0.0",
    "langdetect>=1.0.9",
]
```

**Docker Services (docker-compose.yml):**
- Neo4j 5.x (port 7687, 7474)
- ChromaDB (port 8000)
- Elasticsearch 8.x (port 9200)

---

## 11. Configuration

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
GOFR_IQ_GROUPS_PATH=/app/data/groups

# Neo4j
GOFR_IQ_NEO4J_URI=bolt://neo4j:7687
GOFR_IQ_NEO4J_USER=neo4j
GOFR_IQ_NEO4J_PASSWORD=secret

# ChromaDB
GOFR_IQ_CHROMA_HOST=chromadb
GOFR_IQ_CHROMA_PORT=8000

# Elasticsearch (optional)
GOFR_IQ_ES_HOSTS=http://elasticsearch:9200
GOFR_IQ_ES_USER=elastic
GOFR_IQ_ES_PASSWORD=secret

# Embedding model
GOFR_IQ_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

# LLM Extraction
GOFR_IQ_LLM_PROVIDER=anthropic  # or openai
GOFR_IQ_LLM_MODEL=claude-sonnet-4-20250514
GOFR_IQ_LLM_TEMPERATURE=0.1
GOFR_IQ_LLM_FALLBACK_PROVIDER=openai
ANTHROPIC_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

---

## 12. Phased Build Plan

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
│   └── sample_data.py               # Sample documents, sources, groups, tokens
├── data/                            # Runtime test data (gitignored, auto-created)
│   ├── documents/
│   ├── sources/
│   ├── groups/
│   ├── chroma/
│   └── audit/
└── ...test files...
```

**TestDataStore** creates isolated test environment:
- Creates `test/data/` directory structure
- Populates sample groups with token permissions
- Populates sample sources (assigned to groups)
- Populates sample documents (assigned to groups)
- Creates test JWT tokens with various permission levels
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
| 0.2 | Add sample data generation (2 groups, 3 tokens, 3 sources, 10 docs) | `test_sample_data_generation` |
| 0.3 | Create `test/fixtures/test_servers.py` with `ServerManager` | `test_server_manager_import` |
| 0.4 | Update `conftest.py` with fixtures | `test_fixtures_available` |

**Exit Criteria:** `pytest test/test_infrastructure.py` passes

---

### Phase 1: Pydantic Models
**Goal:** Data models for groups, documents, sources, queries

| Step | Description | Tests |
|------|-------------|-------|
| 1.1 | Create `app/models/group.py` - Group model with token permissions | `test_group_model_valid`, `test_group_token_permissions` |
| 1.2 | Create `app/models/source.py` - Source model with group_guid | `test_source_model_valid`, `test_source_model_invalid` |
| 1.3 | Create `app/models/document.py` - Document model with versioning | `test_document_model_valid`, `test_document_versioning` |
| 1.4 | Add word count validation (max 20,000) | `test_document_word_limit` |
| 1.5 | Create `app/models/query.py` - Query request/response | `test_query_request_model`, `test_query_response_model` |

**Exit Criteria:** `pytest test/test_models.py` passes

---

### Phase 2: Group Registry
**Goal:** Group management with token permissions

| Step | Description | Tests |
|------|-------------|-------|
| 2.1 | Create `app/services/group_registry.py` - create/get | `test_create_group`, `test_get_group` |
| 2.2 | Add token permission management | `test_add_token_to_group`, `test_remove_token_from_group` |
| 2.3 | Add get_token_groups (all groups for a token_id) | `test_get_token_groups` |
| 2.4 | Add get_token_permissions (permissions for token in group) | `test_get_token_permissions` |
| 2.5 | Add list groups | `test_list_groups` |

**Exit Criteria:** `pytest test/test_group_registry.py` passes

---

### Phase 3: Canonical Document Store
**Goal:** JSON file storage with GUID naming, group_guid partitioning

| Step | Description | Tests |
|------|-------------|-------|
| 3.1 | Create `app/services/document_store.py` - basic save/load | `test_save_document`, `test_load_document` |
| 3.2 | Add path partitioning: `{group_guid}/{date}/{guid}.json` | `test_document_path_structure` |
| 3.3 | Add document versioning (link to previous) | `test_document_version_chain` |
| 3.4 | Add list documents by group_guid/date | `test_list_documents_by_group` |

**Exit Criteria:** `pytest test/test_document_store.py` passes

---

### Phase 4: Source Registry
**Goal:** CRUD for sources within groups

| Step | Description | Tests |
|------|-------------|-------|
| 4.1 | Create `app/services/source_registry.py` - create/get | `test_create_source`, `test_get_source` |
| 4.2 | Add list sources by group_guid with filters | `test_list_sources`, `test_filter_sources_by_region` |
| 4.3 | Add update source (audit logged) | `test_update_source`, `test_update_creates_audit` |
| 4.4 | Add soft-delete source | `test_soft_delete_source` |

**Exit Criteria:** `pytest test/test_source_registry.py` passes

---

### Phase 5: Group Access Control
**Goal:** Token validation, token-group resolution, permission enforcement

| Step | Description | Tests |
|------|-------------|-------|
| 5.1 | Create `app/auth/group_access.py` - extract token_id (jti) from JWT | `test_extract_token_id_from_jwt` |
| 5.2 | Add resolve_token_groups (query group registry for token's groups) | `test_resolve_token_groups` |
| 5.3 | Add check_permission (token_id, group_guid, permission) | `test_check_permission_granted`, `test_check_permission_denied` |
| 5.4 | Integration: document store + group access | `test_document_access_by_group` |

**Exit Criteria:** `pytest test/test_group_access.py` passes

---

### Phase 6: Language Detection
**Goal:** Auto-detect document language at ingestion

| Step | Description | Tests |
|------|-------------|-------|
| 6.1 | Create `app/services/language_detector.py` | `test_detect_english`, `test_detect_chinese`, `test_detect_japanese` |
| 6.2 | Integrate with document ingestion | `test_ingest_auto_detects_language` |

**Exit Criteria:** `pytest test/test_language_detection.py` passes

---

### Phase 7: Duplicate Detection
**Goal:** Flag duplicate documents at ingestion

| Step | Description | Tests |
|------|-------------|-------|
| 7.1 | Create `app/services/duplicate_detector.py` - simple hash | `test_exact_duplicate_detection` |
| 7.2 | Add similarity-based detection (cosine similarity on text) | `test_near_duplicate_detection` |
| 7.3 | Integrate with ingest - set `duplicate_of`, `duplicate_score` | `test_ingest_flags_duplicate` |

**Exit Criteria:** `pytest test/test_duplicate_detection.py` passes

---

### Phase 8: LLM Extraction Service
**Goal:** Extract structured metadata from news content using LLM

| Step | Description | Tests |
|------|-------------|-------|
| 8.1 | Create `app/models/event_type.py` - EventType enum and validation | `test_event_type_enum`, `test_event_type_validation` |
| 8.2 | Create `app/models/tag.py` - Tag model and validation | `test_tag_format`, `test_tag_validation` |
| 8.3 | Create `app/services/llm_extraction.py` - base structure | `test_llm_extraction_import` |
| 8.4 | Add Anthropic provider integration | `test_anthropic_extraction` |
| 8.5 | Add OpenAI provider integration | `test_openai_extraction` |
| 8.6 | Add provider fallback logic | `test_provider_fallback` |
| 8.7 | Add extraction prompt with target distributions | `test_extraction_prompt` |
| 8.8 | Add response parsing and validation | `test_extraction_response_parsing` |
| 8.9 | Add ImpactScore extraction with distribution validation | `test_impact_score_distribution` |
| 8.10 | Add HorizonTime extraction and parsing | `test_horizon_time_extraction` |

**Exit Criteria:** `pytest test/test_llm_extraction.py` passes

---

### Phase 9: Basic Ingest Service
**Goal:** Orchestrate ingestion without external indexes (with LLM extraction)

| Step | Description | Tests |
|------|-------------|-------|
| 9.1 | Create `app/services/ingest_service.py` - basic flow | `test_ingest_returns_guid` |
| 9.2 | Validate token has 'create' permission on group | `test_ingest_permission_check` |
| 9.3 | Validate source exists and belongs to same group | `test_ingest_rejects_invalid_source` |
| 9.4 | Validate word count | `test_ingest_rejects_long_document` |
| 9.5 | Detect language | `test_ingest_sets_language` |
| 9.6 | Check duplicates | `test_ingest_flags_duplicate` |
| 9.7 | Call LLM extraction service | `test_ingest_calls_llm_extraction` |
| 9.8 | Handle LLM extraction failure gracefully | `test_ingest_handles_extraction_failure` |
| 9.9 | Store to canonical store with extracted fields | `test_ingest_creates_file_with_extracted` |

**Exit Criteria:** `pytest test/test_ingest_service.py` passes

---

### Phase 10: Basic MCP Tools (No External DBs)
**Goal:** MCP server with ingest/retrieve tools using file store only

| Step | Description | Tests |
|------|-------------|-------|
| 10.1 | Create `app/tools/ingest_tools.py` - `ingest_document` | `test_mcp_ingest_tool` |
| 10.2 | Create `app/tools/source_tools.py` - `list_sources`, `get_source` | `test_mcp_source_tools` |
| 10.3 | Create `app/tools/group_tools.py` - `list_groups`, `get_group` | `test_mcp_group_tools` |
| 10.4 | Create `app/tools/query_tools.py` - `get_document` by GUID | `test_mcp_get_document` |
| 10.5 | Create `app/main.py` - MCP server entry | `test_mcp_server_starts` |
| 10.6 | Integration test with ServerManager | `test_mcp_ingest_end_to_end` |

**Exit Criteria:** `pytest test/test_mcp_tools.py` passes (servers spin up from test fixtures)

---

### Phase 11: Audit Logging
**Goal:** Full audit trail for all operations

| Step | Description | Tests |
|------|-------------|-------|
| 11.1 | Create `app/services/audit_service.py` - log event | `test_audit_log_event` |
| 11.2 | Add audit to ingest | `test_ingest_creates_audit_entry` |
| 11.3 | Add audit to source CRUD | `test_source_crud_audited` |
| 11.4 | Add audit to queries | `test_query_audited` |

**Exit Criteria:** `pytest test/test_audit.py` passes

---

### Phase 12: ChromaDB Integration
**Goal:** Embedding index with configurable chunking

| Step | Description | Tests |
|------|-------------|-------|
| 12.1 | Create `app/services/embedding_index.py` - init ChromaDB | `test_chroma_connection` |
| 12.2 | Add document embedding with chunking | `test_embed_document`, `test_chunking_config` |
| 12.3 | Add similarity search | `test_similarity_search` |
| 12.4 | Test cross-language search | `test_cross_language_similarity` |
| 12.5 | Integrate with ingest service | `test_ingest_creates_embeddings` |

**Exit Criteria:** `pytest test/test_embedding_index.py` passes

---

### Phase 13: Neo4j Integration
**Goal:** Graph index for entity relationships including EventType, Tag, and Company aliases

| Step | Description | Tests |
|------|-------------|-------|
| 13.1 | Create `app/services/graph_index.py` - init Neo4j | `test_neo4j_connection` |
| 13.2 | Create core schema (Group, Source, NewsStory, Company, Sector, Region) | `test_neo4j_core_schema` |
| 13.3 | Create Company node with aliases (ticker, name, multilingual) | `test_company_node_with_aliases` |
| 13.4 | Add company alias resolution (TSM = 2330.TW = TSMC) | `test_company_alias_resolution` |
| 13.5 | Create EventType nodes (controlled vocabulary) | `test_neo4j_event_type_nodes` |
| 13.6 | Create Tag nodes (flexible taxonomy) | `test_neo4j_tag_nodes` |
| 13.7 | Add document node creation with impact_score, horizon_time | `test_create_news_story_node` |
| 13.8 | Add core relationships (BELONGS_TO, PRODUCED_BY, MENTIONS) | `test_create_core_relationships` |
| 13.9 | Add classification relationships (CLASSIFIED_AS, TAGGED_WITH) | `test_create_classification_relationships` |
| 13.10 | Add graph traversal queries | `test_graph_traversal` |
| 13.11 | Integrate with ingest service | `test_ingest_creates_graph_nodes` |

**Exit Criteria:** `pytest test/test_graph_index.py` passes

---

### Phase 14: Query Service (Hybrid Search)
**Goal:** Orchestrate similarity → filter → score → rank flow with time-based boosts

| Step | Description | Tests |
|------|-------------|-------|
| 14.1 | Create `app/services/query_service.py` - basic structure | `test_query_service_init` |
| 14.2 | Add ChromaDB similarity search | `test_query_similarity` |
| 14.3 | Add company alias resolution in queries | `test_query_company_alias_resolution` |
| 14.4 | Add core metadata filtering (date, region, sector, companies) | `test_query_with_core_filters` |
| 14.5 | Add impact_score filtering | `test_query_by_impact_score` |
| 14.6 | Add horizon_time range filtering | `test_query_by_horizon_time` |
| 14.7 | Add event_types filtering | `test_query_by_event_types` |
| 14.8 | Add tags filtering | `test_query_by_tags` |
| 14.9 | Add group scoping (only search permitted groups) | `test_query_respects_groups` |
| 14.10 | Add Neo4j graph enrichment | `test_query_with_graph_context` |
| 14.11 | Add trust level scoring boost | `test_trust_level_scoring` |
| 14.12 | Add recency scoring boost (time decay) | `test_recency_scoring_boost` |
| 14.13 | Add horizon relevance scoring (upcoming vs expired) | `test_horizon_relevance_scoring` |
| 14.14 | Add combined scoring formula | `test_combined_scoring_formula` |
| 14.15 | Add `include_expired` filter option | `test_exclude_expired_by_default` |
| 14.16 | MCP tool: `query_documents` | `test_mcp_query_documents` |

**Exit Criteria:** `pytest test/test_query_service.py` passes

---

### Phase 15: Web API
**Goal:** FastAPI endpoints for non-MCP access

| Step | Description | Tests |
|------|-------------|-------|
| 15.1 | Create `app/web/routes.py` - health endpoint | `test_web_health` |
| 15.2 | Add POST `/api/v1/documents` | `test_web_ingest` |
| 15.3 | Add GET `/api/v1/documents/{guid}` | `test_web_get_document` |
| 15.4 | Add POST `/api/v1/search` with all filter options | `test_web_search` |
| 15.5 | Add source endpoints | `test_web_source_crud` |
| 15.6 | Add group endpoints | `test_web_group_endpoints` |
| 15.7 | Add auth middleware | `test_web_auth_required` |
| 15.8 | Create `app/web_main.py` entry | `test_web_server_starts` |

**Exit Criteria:** `pytest test/test_web_api.py` passes

---

### Phase 16: Index Rebuild & Admin Tools
**Goal:** Incremental rebuild, admin CLI

| Step | Description | Tests |
|------|-------------|-------|
| 16.1 | Create `app/services/index_manager.py` - scan unindexed | `test_find_unindexed_documents` |
| 16.2 | Add incremental rebuild | `test_incremental_rebuild` |
| 16.3 | Add full rebuild | `test_full_rebuild` |
| 16.4 | Add verify mode | `test_verify_indexes` |
| 16.5 | Create `scripts/storage_manager.sh` | `test_storage_manager_help` |
| 16.6 | MCP tool: `rebuild_index` (admin) | `test_mcp_rebuild_index` |

**Exit Criteria:** `pytest test/test_index_manager.py` passes

---

### Phase 17: Docker & Integration
**Goal:** Full stack in containers (without Elasticsearch)

| Step | Description | Tests |
|------|-------------|-------|
| 17.1 | Create `docker/docker-compose.yml` (ChromaDB, Neo4j) | Manual: `docker-compose up` |
| 17.2 | Update Dockerfile.dev for all deps | Manual: container builds |
| 17.3 | Full integration test suite | `test_integration_full_flow` |
| 17.4 | Performance test (1000 docs) | `test_performance_ingest_1000` |
| 17.5 | LLM extraction performance test | `test_llm_extraction_performance` |

**Exit Criteria:** `pytest test/test_integration.py` passes in container

---

### Phase 18 (OPTIONAL): Elasticsearch Integration
**Goal:** Add keyword search with multilingual analyzers for enhanced filtering

*This phase is optional. The system is fully functional with ChromaDB + Neo4j.*

| Step | Description | Tests |
|------|-------------|-------|
| 18.1 | Create `app/services/search_index.py` - init ES client | `test_es_connection` |
| 18.2 | Create index with multilingual mappings (include impact_score, event_types, tags) | `test_es_index_creation` |
| 18.3 | Add document indexing with extracted fields | `test_es_index_document` |
| 18.4 | Add keyword search | `test_es_keyword_search` |
| 18.5 | Add metadata filters (date, region, impact_score, event_types, tags) | `test_es_metadata_filters` |
| 18.6 | Integrate with ingest service | `test_ingest_indexes_in_es` |
| 18.7 | Update query service to use ES for filtering | `test_query_with_es_filters` |
| 18.8 | Update docker-compose.yml to include ES | Manual: ES container runs |

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
| 1 - Models (incl. Group) | 7 | 11 |
| 2 - Group Registry | 5 | 16 |
| 3 - Document Store | 4 | 20 |
| 4 - Source Registry | 4 | 24 |
| 5 - Group Access Control | 4 | 28 |
| 6 - Language Detection | 4 | 32 |
| 7 - Duplicate Detection | 3 | 35 |
| **8 - LLM Extraction Service** | 10 | 45 |
| 9 - Ingest Service | 9 | 54 |
| 10 - MCP Tools | 6 | 60 |
| 11 - Audit | 4 | 64 |
| 12 - ChromaDB | 5 | 69 |
| **13 - Neo4j (with aliases/EventType/Tag)** | 11 | 80 |
| **14 - Query Service (with scoring boosts)** | 16 | 96 |
| 15 - Web API | 8 | 104 |
| 16 - Index Rebuild | 6 | 110 |
| 17 - Integration | 5 | 115 |
| **18 - Elasticsearch (Optional)** | 8 | 123 |

**Core system complete at Phase 17 with 115 tests.**

---

## 13. Open Questions

~~All questions resolved — see Section 1.1 Key Design Decisions.~~

---

## 14. Audit Logging

**Module:** `app/services/audit_service.py`

Full audit trail for all operations:

| Event Type | Data Captured |
|------------|---------------|
| `document.ingest` | guid, source_guid, group_guid, token_id, timestamp, duplicate_status |
| `document.query` | query_text, filters, token_id, group_guids, timestamp, result_count |
| `document.retrieve` | guid, token_id, group_guid, timestamp |
| `source.create` | source_guid, group_guid, token_id, timestamp |
| `source.update` | source_guid, token_id, changes, timestamp |
| `source.delete` | source_guid, token_id, timestamp |
| `group.create` | group_guid, token_id, timestamp |
| `group.update` | group_guid, token_id, changes, timestamp |
| `group.token_add` | group_guid, target_token_id, permissions, token_id, timestamp |
| `group.token_remove` | group_guid, target_token_id, token_id, timestamp |
| `admin.rebuild` | index_type, token_id, timestamp, status |

**Storage:** `data/audit/{YYYY-MM-DD}/audit.jsonl` (append-only JSONL)

---

## 15. Index Rebuild Strategy

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

## 16. Admin Utility Scripts

### 14.1 Token Manager

**Location:** `scripts/token_manager.sh`

Uses `gofr_common.auth` to create and manage JWT tokens:

```bash
# Create a new token for a group with permissions
./token_manager.sh create --group=<group_guid> --permissions=create,read,update,delete --expires=30d

# Add existing token to another group  
./token_manager.sh add-to-group --token-id=<token_id> --group=<group_guid> --permissions=read

# Remove token from a group
./token_manager.sh remove-from-group --token-id=<token_id> --group=<group_guid>

# List all tokens
./token_manager.sh list

# Revoke a token
./token_manager.sh revoke --token-id=<token_id>

# Show token info
./token_manager.sh info --token-id=<token_id>
```

### 14.2 Storage Manager

**Location:** `scripts/storage_manager.sh`

```bash
# Group management
./storage_manager.sh group list
./storage_manager.sh group create <name>
./storage_manager.sh group get <group_guid>
./storage_manager.sh group delete <group_guid>
./storage_manager.sh group list-tokens <group_guid>

# Index management  
./storage_manager.sh rebuild --index=all
./storage_manager.sh rebuild --index=chroma --group=<group_guid>
./storage_manager.sh verify --index=all
./storage_manager.sh stats

# Audit
./storage_manager.sh audit search --token=<token_id> --from=<date> --to=<date>
./storage_manager.sh audit export --format=json --output=audit.json

# Maintenance
./storage_manager.sh vacuum --dry-run
./storage_manager.sh backup --output=/backups/
```

---

**Document updated:** December 8, 2025
