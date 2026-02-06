# GOFR-IQ: Financial News Intelligence Hub

> **APAC-focused news ingestion, semantic search, and client-personalized ranking system.**

GOFR-IQ ingests financial news, analyzes it using LLMs, indexes it in a hybrid Vector+Graph database, and delivers personalized, impact-ranked feeds to clients.

---

## 🚀 Getting Started (5 Minutes)

**[→ Go to Getting Started](docs/getting-started.md)** — Install and run the full stack.

---

## 📚 Documentation

### Core Guides
- **[Getting Started](docs/getting-started.md)** — Installation, Quick Start and Dev Setup
- **[Functional Summary](docs/features/functional_summary.md)** — **High-level technical overview of Graph/Vector RAG**
- **[Neo4j Cypher Guide](simulation/docs/neo4j_queries.md)** — Comprehensive graph query reference dictionary

### Architecture & Features
- **[Hybrid Search](docs/features/hybrid-search.md)** — Vector + Graph search algorithms
- **[Ingestion Pipeline](docs/features/document-ingestion.md)** — 10-step data processing flow
- **[Client Feeds](docs/features/client-feeds.md)** — Personalization and ranking logic
- **[Impact Ranking](docs/features/impact-ranking.md)** — Scoring news by market impact
- **[Graph Schema](docs/features/graph-as-csv.csv)** — Node and relationship definitions

### Reference
- **[Scripts Reference](scripts/readme.md)** — All management commands
- **[Development](docs/development.md)** — Tests, contributions, code style
- **[OpenWebUI Integration](docs/openwebui/)** — Connect GOFR-IQ to LLM chat interfaces

---

## ⚡ Common Commands

```bash
# First time: start with --fresh
./docker/start-prod.sh --fresh --openrouter-key sk-or-v1-YOUR-KEY

# Restart: reuses existing secrets
./docker/start-prod.sh

# See full status
./scripts/dump_environment.sh --docker

# Run tests
./scripts/run_tests.sh

# Load demo data
python demo/load_demo_data.py --mcpo-url http://localhost:8081
```

---

## 🏗️ How It Works

```
News Sources → Ingestion → Vector DB (ChromaDB) ⟷ Knowledge Graph (Neo4j)
                ↓
            LLM Analysis (OpenRouter) → Impact Ranking → Client Feeds
```

**Core Services:**
- **MCP Server** (port 8080) — Core logic, search, ingestion
- **Web API** (port 8082) — Health checks
- **Neo4j** (port 7474) — Knowledge graph
- **ChromaDB** (port 8000) — Vector search
- **Vault** (port 8201) — Secrets & auth

---

## 📂 Project Structure

| Directory | Purpose |
|-----------|---------|
| `app/` | Core application code (MCP servers, Web) |
| `docker/` | Container orchestration & startup scripts |
| `docs/` | Comprehensive documentation |
| `scripts/` | Management utilities (bootstrap, tests, etc.) |
| `lib/gofr-common/` | Shared auth, configs, schemas |
| `test/` | Unit & integration tests |

---

## 🔐 Security & Keys

- **Vault** stores JWT secrets, database credentials, API keys
- **Bootstrap tokens** (365 days) for operators
- **AppRole** per-service auth (Zero-Trust)
- Secrets stored in `secrets/` directory (add to `.gitignore`)

See [Key Management](scripts/readme.md#-key-management-bootstrappy) for details.

---

**License**: Proprietary / See LICENSE.


