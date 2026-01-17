# GOFR-IQ: Financial News Intelligence Platform

> **APAC-focused news ingestion, semantic search, and client-personalized ranking system.**

GOFR-IQ ingests financial news, analyzes it using LLMs, indexes it in a hybrid Vector+Graph database, and delivers personalized, impact-ranked feeds to clients.

---

## 🚀 Quick Links

**New here? Start with:**
- [Getting Started](docs/getting-started.md) — install, run, verify in minutes
- [Configuration](docs/configuration.md) — minimal required env vars + ports
- [Architecture](docs/architecture/overview.md) — how data and requests flow
- [Development](docs/development.md) — tests, style, contribution checklist

---

## ⚡ The 3 Commands (cheat sheet)

- Install & bootstrap (prod): `./docker/start-prod.sh --fresh`
- Run tests (dev): `./scripts/run_tests.sh` (add `--refresh-env` on first run or after pulling secrets)
- Restart services: `./docker/start-prod.sh`

---

## 🧪 Testing Modes

| Mode | Command | Notes |
|------|---------|-------|
| Unit (default) | `./scripts/run_tests.sh --mode unit` | Fast inner-loop run; skips infra/servers. Same as running with no flags. |
| Integration | `./scripts/run_tests.sh --mode integration --refresh-env` | Starts Vault/Chroma/Neo4j plus MCP/MCPO/Web; add `--refresh-env` when secrets/configs change. |
| All | `./scripts/run_tests.sh --mode all --refresh-env` | Runs unit + integration suites sequentially with full infrastructure. |

> `--refresh-env` regenerates `docker/.env` and `config/generated/secrets.env`; use it on first run, after onboarding a new machine, or whenever Vault data changes.

---

## 🏗️ System Overview

```
┌─────────────┐
│   Sources   │  Reuters, Bloomberg, Alt-data
└──────┬──────┘
       ▼
┌────────────────────┐
│ Ingestion Pipeline │  Language Detect -> Duplicate Check -> LLM Extraction
└──────┬─────────────┘
       │
       ├────► Vector Store (ChromaDB)
       │       └─ Semantic Search
       │
       └────► Knowledge Graph (Neo4j)
               └─ Entity Relationships
```

### Core Features
*   **Multi-Language Ingestion**: English, Chinese, Japanese, Korean, Thai, Indonesian.
*   **Hybrid Search**: Combines semantic vector search with graph traversal.
*   **Impact Ranking**: LLM-determined importance (Platinum/Gold/Silver/Bronze).
*   **Client Personalization**: Re-ranks news based on client portfolios.
*   **Secure Access**: Group-based visibility using Vault & JWTs.

---

## 📂 Project Structure

*   `app/`: Core application code (MCP servers, Web API).
*   `docker/`: Container orchestration and startup scripts.
*   `docs/`: Comprehensive documentation.
*   `scripts/`: Utility scripts for management and testing.
*   `test/`: Unit and Integration tests.

---

**License**: Proprietary / See LICENSE.


