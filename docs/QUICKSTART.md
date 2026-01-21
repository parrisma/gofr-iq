# GOFR-IQ Quick Start (5 Minutes)

**Goal**: Get the system running and verify it's healthy.

## Prerequisites

- **Docker** 20.10+ with Compose
- **OpenRouter API Key** (for LLM features) — get one free at [openrouter.ai](https://openrouter.ai)
- **8GB RAM** minimum (16GB recommended)

## Install & Run

```bash
# 1. Clone
git clone https://github.com/parrisma/gofr-iq.git
cd gofr-iq

# 2. Start (first time adds --fresh to init Vault)
./docker/start-prod.sh --fresh --openrouter-key sk-or-v1-YOUR-KEY

# 3. Verify health
docker compose -f docker/docker-compose.yml ps

# 4. Test the API
curl http://localhost:8082/health
```

**Time**: ~8 minutes (includes container pulls and Vault init).

## What Just Happened?

| Component | Status | URL |
|-----------|--------|-----|
| **Vault** (Auth) | Running | http://localhost:8201 |
| **MCP Server** (Core Logic) | Running | http://localhost:8080 |
| **Neo4j** (Knowledge Graph) | Running | http://localhost:7474 |
| **ChromaDB** (Vector Search) | Running | http://localhost:8000 |
| **Web API** (Health/Info) | Running | http://localhost:8082 |

Run `dump_environment.sh` to see full details:
```bash
./scripts/dump_environment.sh --docker
```

## Next Steps

- **Demo Data**: Load ~30 sample stories → `python demo/load_demo_data.py --mcpo-url http://localhost:8081`
- **Run Tests**: `./scripts/run_tests.sh`
- **Read More**: [Full documentation](readme.md) | [Architecture](architecture/overview.md) | [Development](development.md)

## Restart Services

```bash
./docker/start-prod.sh  # No --fresh needed; reuses existing secrets
```

## Troubleshoot

| Issue | Fix |
|-------|-----|
| "Port already in use" | Kill: `docker compose -f docker/docker-compose.yml down` |
| "Vault not ready" | Wait 10s and retry start command |
| "Invalid API key" | Pass correct `--openrouter-key` or set `GOFR_IQ_OPENROUTER_API_KEY` env var |

## Need Help?

- **Setup issue?** See [Getting Started](getting-started.md)
- **Configuration?** See [Configuration](configuration.md)
- **Architecture?** See [System Overview](architecture/overview.md)
- **Scripts?** See [Script Reference](../scripts/readme.md)
