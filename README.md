# GOFR-IQ: Financial News Intelligence Platform

> **APAC-focused news ingestion, semantic search, and client-personalized ranking system**

## What is GOFR-IQ?

GOFR-IQ is a financial news intelligence platform that helps brokerages deliver personalized, impact-ranked news to their clients. It solves the problem of information overload by:

1. **Ingesting** multi-language financial news from diverse sources
2. **Analyzing** content using LLMs to extract market impact, events, and instrument mentions
3. **Indexing** via hybrid vector+graph search for semantic retrieval
4. **Ranking** news by relevance to individual client portfolios and watchlists
5. **Enforcing** group-based access control for content segregation

**Real-World Use Case**: A hedge fund client with holdings in AAPL and TSLA receives high-impact news about these companies first, while screening out irrelevant stories. A basic retail client sees only public newswire content.

---

## Core Capabilities

### 🔍 **Intelligent Content Ingestion**
- Multi-language support (English, Chinese, Japanese, Korean, Thai, Indonesian)
- Automatic language detection
- Duplicate detection (exact and near-duplicate matching)
- LLM-powered extraction of impact scores, events, and entities
- 20,000 word limit per document

### 🔎 **Hybrid Search**
- **Vector Search**: ChromaDB embeddings for semantic similarity
- **Graph Traversal**: Neo4j relationships for entity-based discovery
- **Combined Scoring**: Weighted hybrid results with trust-level boosting

### 📊 **Graph-Based Ranking**
- Impact tiers (Platinum/Gold/Silver/Bronze) for market-moving events
- Entity relationships (companies, instruments, sectors, events)
- Time-decay scoring for freshness
- Trust-level weighting by source reliability

### 👤 **Client Personalization**
- Portfolio-aware ranking (boost news affecting holdings)
- Watchlist integration
- Client profile types (hedge fund, long-only, basic retail)
- Dynamic feed generation based on permissions

### 🔐 **Group Access Control**
- JWT-based authentication
- Multi-group token support
- Group-scoped content visibility
- Public/private content separation

---

## How It Works

```
┌─────────────┐
│   Sources   │  Reuters, Bloomberg, Alt-data providers
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────┐
│         Ingestion Pipeline              │
│  1. Validate source                     │
│  2. Detect language                     │
│  3. Check duplicates                    │
│  4. LLM extraction (impact, entities)   │
└──────┬──────────────────────────────────┘
       │
       ├────► Document Store (File System)
       │
       ├────► ChromaDB (Vector Embeddings)
       │
       └────► Neo4j (Knowledge Graph)
                     │
                     ▼
              ┌─────────────┐
              │ Query Layer │
              └──────┬──────┘
                     │
       ┌─────────────┼─────────────┐
       │             │             │
       ▼             ▼             ▼
   Semantic      Graph          Client
    Search      Traversal       Feeds
```

**Data Flow**:
1. **Ingest**: Document arrives → validated → analyzed → stored in 3 layers
2. **Query**: User query → embedded → searches vector DB + graph DB → merged results
3. **Rank**: Results scored by relevance + impact + trust + client portfolio match
4. **Filter**: Group permissions applied → returned to client

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)
- 4GB+ RAM

### 1. Run Production Stack (Recommended)

```bash
# Clone and enter repository
git clone https://github.com/parrisma/gofr-iq.git
cd gofr-iq

# Start production stack with authentication enabled
cd docker && ./start-swarm.sh
```

**Production services will start on**:
- MCP Server: `http://localhost:8080`
- MCPO (REST API): `http://localhost:8081`
- Web UI: `http://localhost:8082`
- Vault: `http://localhost:8201`
- ChromaDB: `http://localhost:8000`
- Neo4j: `http://localhost:7474` (Bolt: 7687)

**Note**: Production mode has authentication enabled. See [Bootstrap Guide](docs/getting-started/bootstrap.md) for creating groups and tokens.

### 2. Run Development Environment

```bash
# Build and start dev container
cd docker && ./build-dev.sh && ./run-dev.sh

# Enter dev container
docker exec -it gofr-iq-dev bash

# Run tests to verify setup
bash scripts/run_tests.sh
```

**Dev services will start on** (offset +200 from prod):
- MCP Server: `http://localhost:8280`
- MCPO (REST API): `http://localhost:8281`
- Web UI: `http://localhost:8282`
- ChromaDB: `http://localhost:8100`
- Neo4j: `http://localhost:7574` (Bolt: 7787)

### 3. Local Development

```bash
# Install dependencies with uv
uv venv && source .venv/bin/activate
uv pip install -e .

# Start infrastructure (ChromaDB + Neo4j)
cd docker && docker compose up -d chromadb neo4j

# Run MCP server
python -m app.main_mcp --no-auth

# Run tests
bash scripts/run_tests.sh --no-infra
```

### 3. First Steps

```python
# Ingest a document
from app.services import create_ingest_service, create_document_store, create_source_registry

ingest = create_ingest_service(
    document_store=create_document_store(),
    source_registry=create_source_registry()
)

result = ingest.ingest_document(
    source_guid="reuters-guid",
    title="Apple Announces Record Earnings",
    content="Apple Inc. reported record quarterly earnings...",
    language="en"
)
print(f"Document ingested: {result.guid}")

# Query documents
from app.services import create_query_service

query = create_query_service()
results = query.query_documents(
    query_text="Apple earnings",
    permitted_groups=["public"],
    k=10
)

for doc in results.documents:
    print(f"{doc.title} (score: {doc.score:.2f})")
```

---

## Documentation

### 📚 Getting Started
- [Quick Start Guide](docs/getting-started/quick-start.md) - Get running in 5 minutes
- [Installation](docs/getting-started/installation.md) - Detailed setup instructions
- [Configuration](docs/getting-started/configuration.md) - Environment variables and settings

### 🏗️ Architecture
- [System Overview](docs/architecture/overview.md) - Components and data flow
- [Authentication](docs/architecture/authentication.md) - JWT auth and group access
- [Graph Design](docs/architecture/graph-design.md) - Neo4j schema and relationships
- [Hybrid Search](docs/features/hybrid-search.md) - Vector + graph search strategy

### ✨ Features
- [Document Ingestion](docs/features/document-ingestion.md) - How documents are processed
- [Client Feeds](docs/features/client-feeds.md) - Personalized ranking algorithm
- [Group Access Control](docs/features/group-access.md) - Permission model

### 🔧 Development
- [Testing Guide](docs/development/testing.md) - Running and writing tests
- [Version Policy](docs/development/version-policy.md) - Dependency management
- [Contributing](docs/development/contributing.md) - How to contribute

### 📖 Reference
- [Project Summary](docs/PROJECT_SUMMARY.md) - High-level overview
- [Implementation Details](docs/IMPLEMENTATION.md) - Technical specifications
- [Design Review](docs/design-review-report.md) - Architecture analysis

---

## Architecture at a Glance

### Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **API** | FastMCP, FastAPI, MCPO | MCP server, REST wrapper, web interface |
| **Vector DB** | ChromaDB 0.5.23 | Semantic embeddings and similarity search |
| **Graph DB** | Neo4j 6.0.3 | Knowledge graph and relationship traversal |
| **LLM** | OpenRouter API | Impact extraction and entity recognition |
| **Language** | Python 3.11+ | Core application logic |
| **Storage** | File system | Document persistence |
| **Auth** | JWT, Vault | Token-based authentication |

### Key Services

```python
IngestService       # Orchestrates document ingestion pipeline
QueryService        # Hybrid search and ranking
GraphIndex          # Neo4j operations and client feed generation
EmbeddingIndex      # ChromaDB vector operations
LLMService          # OpenRouter API for extraction
SourceRegistry      # News source management
GroupService        # Access control enforcement
```

### Data Models

- **Document**: Core content unit (title, content, metadata, version chain)
- **Source**: News provider (trust level, region, boost factor)
- **GraphNode**: Neo4j entities (Document, Company, Instrument, Event, Client)
- **Client**: User profile with portfolio and watchlist

---

## MCP Tools

GOFR-IQ exposes these tools via Model Context Protocol:

### Ingest Tools
| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `ingest_document` | Store and index a document | `source_guid`, `title`, `content`, `language` |
| `validate_document` | Dry-run validation before ingestion | `source_guid`, `title`, `content` |

### Query Tools
| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `query_documents` | Semantic search with filters | `query_text`, `k`, `impact_tiers`, `date_range` |
| `get_client_feed` | Personalized news for client | `client_guid`, `k`, `impact_threshold` |
| `get_instrument_news` | News for specific ticker | `ticker`, `k`, `impact_tiers` |

### Source Tools
| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `list_sources` | List available sources | `source_type`, `region`, `active_only` |
| `get_source` | Get source details | `source_guid` |
| `create_source` | Register a news provider | `name`, `type`, `trust_level`, `region` |
| `update_source` | Update source properties | `source_guid`, `name`, `trust_level`, `region` |
| `delete_source` | Soft-delete (deactivate) source | `source_guid` |

### Client Tools
| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_client` | Create a new client profile | `name`, `client_type` |
| `list_clients` | List all accessible clients | `client_type` |
| `get_client_profile` | Get full client profile | `client_guid` |
| `update_client_profile` | Update client settings | `client_guid`, `alert_frequency`, `impact_threshold` |
| `add_to_portfolio` | Add stock to portfolio | `client_guid`, `ticker`, `shares` |
| `remove_from_portfolio` | Remove stock from portfolio | `client_guid`, `ticker` |
| `get_portfolio_holdings` | Get portfolio with weights | `client_guid` |
| `add_to_watchlist` | Add stock to watchlist | `client_guid`, `ticker` |
| `remove_from_watchlist` | Remove from watchlist | `client_guid`, `ticker` |
| `get_watchlist_items` | Get watchlist with alerts | `client_guid` |

### Graph Tools
| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `explore_graph` | Traverse entity relationships | `node_guid`, `node_type`, `depth` |

### Health Tools
| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `health_check` | System health status | - |

### Parameter Enums Reference

| Parameter | Values | Notes |
|-----------|--------|-------|
| `client_type` | `HEDGE_FUND\|LONG_ONLY\|QUANT\|PENSION\|FAMILY_OFFICE` | Investment style |
| `impact_tiers` | `PLATINUM (>$1B)\|GOLD (>$100M)\|SILVER (>$10M)\|BRONZE\|STANDARD` | Market impact |
| `source_type` | `news_agency\|internal\|research\|government\|corporate\|social\|other` | Source category |
| `trust_level` | `high (1.2x)\|medium (1.0x)\|low (0.8x)\|unverified (0.6x)` | Scoring boost |
| `alert_frequency` | `realtime\|hourly\|daily\|weekly` | Notification timing |
| `horizon` | `short (<1mo)\|medium (1-6mo)\|long (>6mo)` | Investment horizon |
| `relationship_types` | `AFFECTS\|PEER_OF\|MENTIONS\|HOLDS\|WATCHES\|ISSUED_BY\|BELONGS_TO` | Graph edges |
| `event_types` | `EARNINGS_BEAT\|EARNINGS_MISS\|M&A_ANNOUNCE\|FDA_APPROVAL\|GUIDANCE_RAISE\|GUIDANCE_CUT` | News events |

### Error Codes Reference

All tools return standardized error codes with actionable recovery strategies:

| Category | Error Code | Recovery Strategy |
|----------|------------|-------------------|
| **Auth** | `AUTH_REQUIRED` | Pass `auth_tokens` parameter or include `Authorization: Bearer <token>` header |
| **Auth** | `PERMISSION_DENIED` | Verify token has access to the requested resource |
| **Client** | `CLIENT_NOT_FOUND` | Call `list_clients` to discover valid `client_guid` values |
| **Client** | `CLIENT_CREATE_FAILED` | Check required fields: `name` (string), `client_type` (enum) |
| **Source** | `SOURCE_NOT_FOUND` | Call `list_sources` to discover valid `source_guid` values |
| **Source** | `SOURCE_CREATE_FAILED` | Call `create_source` with `name`, `type`, `trust_level` |
| **Portfolio** | `PORTFOLIO_NOT_FOUND` | Call `get_client_profile` to check if client has portfolio |
| **Portfolio** | `HOLDING_NOT_FOUND` | Call `get_portfolio_holdings` to see positions; use `add_to_portfolio` if needed |
| **Watchlist** | `WATCHLIST_NOT_FOUND` | Call `get_client_profile` to check if client has watchlist |
| **Watchlist** | `WATCH_NOT_FOUND` | Call `get_watchlist_items` to see watched stocks; use `add_to_watchlist` if needed |
| **Graph** | `GRAPH_NOT_AVAILABLE` | Run `health_check` to verify Neo4j connectivity |
| **Graph** | `NODE_NOT_FOUND` | Verify `node_guid` and `node_type` match existing graph entities |
| **Query** | `QUERY_SEARCH_FAILED` | Check `filters_applied` in error details; verify ticker format (e.g., "AAPL") |
| **Ingest** | `DOCUMENT_TOO_LONG` | Split document into chunks ≤20,000 words |
| **Validation** | `INVALID_*` | Check error details for valid enum values |

**Error Response Format**:
```json
{
  "success": false,
  "error_code": "CLIENT_NOT_FOUND",
  "message": "Client abc-123 not found",
  "recovery_strategy": "Call list_clients to discover valid client_guid values",
  "details": {"client_guid": "abc-123"}
}
```

**Example MCP Call**:
```bash
# Via mcpo REST API
curl -X POST http://localhost:8181/query_documents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "query_text": "semiconductor shortage impact",
    "k": 10,
    "impact_tiers": ["PLATINUM", "GOLD"]
  }'
```

---

## Configuration

### Environment Variables

Set in `scripts/gofriq.env` or environment:

```bash
# LLM Configuration (Optional - for extraction)
GOFR_IQ_OPENROUTER_API_KEY=sk-or-...
GOFR_IQ_CHAT_MODEL=anthropic/claude-opus-4
GOFR_IQ_EMBEDDING_MODEL=qwen/qwen3-embedding-8b

# Database Endpoints
GOFR_IQ_CHROMADB_HOST=localhost
GOFR_IQ_CHROMADB_PORT=8000
GOFR_IQ_NEO4J_URI=bolt://localhost:7687
GOFR_IQ_NEO4J_USER=neo4j
GOFR_IQ_NEO4J_PASSWORD=password

# Authentication
GOFR_IQ_JWT_SECRET=your-secret-key
GOFR_AUTH_BACKEND=vault  # or 'file' or 'memory'
GOFR_VAULT_URL=http://localhost:8200

# Server Ports
GOFR_IQ_MCP_PORT=8180
GOFR_IQ_MCPO_PORT=8181
GOFR_IQ_WEB_PORT=8182

# Storage
GOFR_IQ_STORAGE_DIR=data/storage
```

### Feature Flags

```bash
GOFR_IQ_NO_AUTH=false           # Disable authentication
GOFR_IQ_ENABLE_GRAPH=true       # Enable Neo4j integration
GOFR_IQ_ENABLE_LLM=true         # Enable LLM extraction
```

---

## Testing

**712 passing tests, 1 skipped, 0 failures**

```bash
# Full test suite with infrastructure
bash scripts/run_tests.sh --all

# Unit tests only (no Docker services)
bash scripts/run_tests.sh --no-infra

# Specific test file
uv run pytest test/test_ingest_service.py -v

# With coverage
uv run pytest --cov=app --cov-report=html
```

**Test Categories**:
- Unit tests: Services, models, utilities (no external dependencies)
- Integration tests: ChromaDB, Neo4j, Vault interactions
- LLM tests: OpenRouter API calls (requires API key)
- End-to-end tests: Full ingestion → query → ranking pipeline

**Infrastructure**: Tests automatically start/stop Docker containers (Neo4j, ChromaDB, Vault) in ephemeral mode.

---

## Project Status

- **Version**: 0.1.0 (Beta)
- **Python**: 3.11+
- **Test Coverage**: 76%
- **Test Pass Rate**: 100% (712/712)
- **Last Updated**: January 2026
- **License**: MIT
- **Status**: Active Development

---

## Contributing

Contributions welcome! See [Contributing Guide](docs/development/contributing.md).

**Development Workflow**:
1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run `bash scripts/run_tests.sh --all`
5. Submit pull request

---

## Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/parrisma/gofr-iq/issues)
- **Discussions**: [GitHub Discussions](https://github.com/parrisma/gofr-iq/discussions)

---

## License

MIT License - see [LICENSE](LICENSE) for details.


