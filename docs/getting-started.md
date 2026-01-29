# Getting Started with GOFR-IQ

This guide covers everything from a quick start to a full production deployment.

You’ll accomplish:
- Start the stack (prod) or dev infra
- Verify health
- Optionally load demo data

## Prerequisites

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| **OS** | Linux/macOS | Ubuntu 22.04+ / macOS 13+ |
| **Python** | 3.11 | 3.12 (with pip, venv) |
| **Docker** | 20.10 | 25.0+ (with Compose 2.0+) |
| **Memory** | 8 GB | 16 GB (for Neo4j + ChromaDB) |
| **API Keys**| OpenRouter | Required for LLM features |

---

## ⚡ Quick Start (5 Minutes)

Use this method to spin up the full production stack using Docker.

### 1. Clone & Setup

```bash
git clone https://github.com/parrisma/gofr-iq.git
cd gofr-iq
```

### 2. Start Production Stack

We provide a single wrapper script that handles config, secrets, and container startup.

```bash
# First time install (initializes Vault & Secrets)
./scripts/start-prod.sh --fresh --openrouter-key sk-or-v1-YOUR-KEY

# Restarting (reuses existing secrets)
./scripts/start-prod.sh
```

**What happens:**
- 🔐 Vault initialized & unsealed automatically
- 🗝️ Admin & Public tokens generated/retrieved
- 🏗️ Containers started (MCP, Web, Vault, Neo4j, ChromaDB)
- 📝 Configuration merged into `docker/.env`
- ⏱️ Time: ~8 minutes first run, ~2 minutes restart

### 3. Verify Health

**Service Status Table:**

| Component | Status | URL | Description |
|-----------|--------|-----|-------------|
| **Vault** | Running | http://localhost:8201 | Auth & Secrets |
| **MCP Server** | Running | http://localhost:8080 | Core Logic |
| **Neo4j** | Running | http://localhost:7474 | Knowledge Graph |
| **ChromaDB** | Running | http://localhost:8000 | Vector Search |
| **Web API** | Running | http://localhost:8082 | Health/Info |

Check detailed status:
```bash
docker compose -f docker/docker-compose.yml ps
# Or use the helper script for a full env dump
./scripts/dump_environment.sh --docker
```

All services should be `healthy`. Open [http://localhost:8082](http://localhost:8082) to check the Web API.

### 4. Load Demo Data (Optional)

Populate the system with realistic APAC financial news and client portfolios.

```bash
# Load 30 fictional stories into the system
python demo/load_demo_data.py --mcpo-url http://localhost:8081

# See what's included
cat demo/readme.md
```
Outcome: demo clients and ~30 stories available for search.

### 5. Synthetic Simulation (Optional)

Generate richer, scenario-based stories for realistic testing:

```bash
uv run simulation/run_simulation.py --count 30 --output simulation/test_output
```
See [simulation/readme.md](../simulation/readme.md) for details and token setup.

---

## 🛠️ Development Setup

For contributors who want to run code locally or modify the codebase.

### 1. Python Environment

```bash
# Create venv
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies (using uv is recommended for speed)
pip install uv
uv pip install -e .
```

### 2. Configuration

Copy the example environment and add your keys:

```bash
cp scripts/gofriq.env.example scripts/gofriq.env
# Edit to add your OPENROUTER_API_KEY
nano scripts/gofriq.env
```

### 3. Start Infrastructure Only (Dev)

Run the databases in Docker while running Python code locally.

```bash
cd docker
./run-dev.sh
# Dev ports (offset from prod): Neo4j 7574, ChromaDB 8100
```

### 4. Minimal no-auth loop (fastest way to poke)

```bash
# In one terminal: start dev infra (above)

# In another terminal: run MCP without auth
python -m app.main_mcp --no-auth

# Call it
curl http://localhost:8280/health
```

### 6. Run Tests

```bash
# Runs the full suite
./scripts/run_tests.sh
```

---

## 🔄 Lifecycle Management

### Working with Vault Secrets

To inspect or manage groups and tokens in Vault:

```bash
# One-liner: load Vault env (mints short-lived operator token) and list groups
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
./lib/gofr-common/scripts/auth_manager.sh --docker groups list
./lib/gofr-common/scripts/auth_manager.sh --docker tokens list
```

This workflow:
1. `auth_env.sh` — mints a 1-hour operator token (least-privilege) from your root token, and reads the JWT secret.
2. Exports `VAULT_ADDR`, `VAULT_TOKEN` (short-lived), and `GOFR_JWT_SECRET`.
3. `auth_manager.sh` then runs using these credentials to inspect/manage auth objects.

**Note**: No secrets are written to disk; all are held in memory for that shell session.

### Restarting Production
If you need to restart the stack (e.g. after a reboot):

```bash
# Stops containers
cd docker && docker compose down

# Start up again (auto-unseals Vault)
./start-prod.sh
```

### Resetting Everything (Nuke & Pave)
To wipe all data (databases, vaults, secrets) and start fresh:

```bash
./scripts/start-prod.sh --reset
```
**Warning**: This deletes all data in `gofr-iq/data/`.

---

## 🔍 Service Ports

| Service | Prod Port | Dev Port | Description |
|---------|-----------|----------|-------------|
| **MCP Server** | 8080 | 8280 | Model Context Protocol |
| **MCPO API** | 8081 | 8281 | OpenAPI Wrapper |
| **Web API** | 8082 | 8282 | REST Health/Metrics |
| **Vault** | 8201 | 8200 | Secret Management |
| **Neo4j** | 7474 | 7574 | Graph Database |
| **ChromaDB** | 8000 | 8100 | Vector Database |

For explicit configuration details, see [Configuration Guide](configuration.md).

---

## 🔧 Troubleshooting

| Issue | Typical Cause | Fix |
|-------|---------------|-----|
| **"Port already in use"** | Another service (or dev instance) running | Stop conflicts: `docker compose -f docker/docker-compose.yml down` |
| **"Vault not ready"** | Initialization taking time | Wait 10s and retry the start command |
| **"Invalid API key"** | Missing or bad OpenRouter key | Pass correct `--openrouter-key` or set `GOFR_IQ_OPENROUTER_API_KEY` env var |
| **Neo4j/Chroma OOM** | Insufficient RAM (Limit: 8GB) | Ensure Docker Desktop has allocated at least 8GB RAM |
| **"Auth Error"** in logs | Expired or missing tokens | Run `./scripts/start-prod.sh` (without --fresh) to refresh tokens |

