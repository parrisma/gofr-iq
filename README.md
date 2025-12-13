# GOFR-IQ: APAC Brokerage News Repository

MCP server for ingesting, indexing, and querying financial news with graph-based ranking and client-specific relevance scoring.

## Features

- **Document Ingestion**: Multi-language support (EN, ZH, JA, KO), duplicate detection, 20K word limit
- **Hybrid Search**: ChromaDB embeddings + Neo4j graph traversal
- **Graph-Based Ranking**: LLM-extracted impact scores, event types, instrument mentions
- **Client Personalization**: Portfolio/watchlist-aware news feeds with time decay
- **Group Access Control**: JWT-based permission boundaries

## Architecture

```
MCP (8060) ─┐
MCPO (8061) ├─► Services ─► ChromaDB (embeddings) + Neo4j (graph)
Web (8062) ─┘
```

## Quick Start

```bash
# Build and run
cd docker && ./build-dev.sh && ./run-dev.sh

# Enter container
docker exec -it gofr-iq-dev bash

# Run tests (auto-starts Neo4j + ChromaDB)
bash scripts/run_tests.sh

# Start MCP server
python -m app.main_mcp --no-auth
```

## MCP Tools

| Tool | Purpose |
|------|---------|
| `ingest_document` | Store document with LLM extraction |
| `query_documents` | Semantic search with impact filters |
| `get_client_feed` | Ranked news for client portfolio |
| `explore_graph` | Traverse relationships |
| `get_instrument_news` | News by ticker |

## Configuration

Set in `scripts/gofriq.env`:
- `GOFR_IQ_OPENROUTER_API_KEY` - LLM for extraction (optional)
- `GOFR_IQ_CHROMADB_HOST` - ChromaDB endpoint
- `GOFR_IQ_NEO4J_URI` - Neo4j endpoint

## Tests

605 tests, 76% coverage. Infrastructure containers auto-start.

```bash
bash scripts/run_tests.sh          # Full suite with infra
bash scripts/run_tests.sh --no-infra  # Unit tests only
```

## License

MIT
