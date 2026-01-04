# GOFR-IQ Project Summary

## Overview

APAC Brokerage News Repository with graph-based ranking and client-specific relevance scoring.

## Core Services

| Service | Purpose |
|---------|---------|
| `IngestService` | Document storage, LLM extraction, duplicate detection |
| `QueryService` | Hybrid search (embedding + graph), scoring |
| `GraphIndex` | Neo4j operations, client feeds, traversal |
| `EmbeddingIndex` | ChromaDB vector storage, similarity search |
| `SourceRegistry` | News source CRUD with group permissions |

## Key Models

- **Document**: Immutable, versioned, max 20K words, auto language detection
- **Source**: News provider with trust level, region, boost factor
- **Group**: Permission boundary (documents, sources, clients scoped to groups)
- **Client**: Portfolio, watchlist, preferences for personalized feeds

## Graph Schema

**Nodes**: Document, Source, Company, Instrument, EventType, Client, Portfolio, Watchlist  
**Key Relations**: `IN_GROUP` (permissions), `AFFECTS` (impact), `HOLDS`/`WATCHES` (client interests)

## Scoring Formula

```
relevance = impact_score × decay + position_boost + watchlist_boost

Decay by tier: PLATINUM(0.05) → GOLD(0.10) → SILVER(0.15) → BRONZE(0.20) → STANDARD(0.30)
```

## Ports

| Service | Port |
|---------|------|
| MCP | 8060 |
| MCPO | 8061 |
| Web | 8062 |
| Neo4j (test) | 7475/7688 |
| ChromaDB (test) | 8101 |

## Environment

Config via `scripts/gofriq.env`. Key variables:
- `GOFR_IQ_OPENROUTER_API_KEY` - LLM extraction
- `GOFR_IQ_JWT_SECRET` - Authentication
- `GOFR_IQ_CHROMADB_HOST`, `GOFR_IQ_NEO4J_URI` - Infrastructure

## Tests

605 tests, 76% coverage. Run with `bash scripts/run_tests.sh`.
