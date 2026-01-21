# Management Scripts Reference

Complete index of management scripts across GOFR-IQ and gofr-common, organized by category and location.

## 📋 Quick Index

| Category | Location | Key Scripts |
|----------|----------|-------------|
| **Vault & Auth** | `lib/gofr-common/scripts/` | `auth_env.sh`, `auth_manager.sh`, `bootstrap_auth.sh` |
| **Bootstrap & Setup** | `scripts/` | `bootstrap.py`, `setup_approle.py`, `generate_envs.sh` |
| **Docker Ops** | `docker/` | `start-prod.sh`, `run-dev.sh`, `build-*.sh` |
| **Document Ops** | `scripts/` | `manage_document.sh`, `manage_source.sh` |
| **Simulation** | `simulation/` | `run_simulation.py`, `generate_synthetic_*.py` |
| **Testing** | `scripts/`, `simulation/` | `run_tests.sh`, `validate_*.py` |

---

## 🔐 Vault & Auth Management

Location: **`lib/gofr-common/scripts/`**

### auth_env.sh
**Purpose:** Mint short-lived operator token and emit Vault env vars for sourcing.

**Usage:**
```bash
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
```

**Features:**
- Reads root token from `secrets/vault_root_token`
- Mints 1h operator token with least-privilege policy
- Reads JWT signing secret from Vault
- Exports: `VAULT_ADDR`, `VAULT_TOKEN`, `GOFR_JWT_SECRET`
- Falls back to `docker exec gofr-vault` if vault CLI unavailable
- Zero secrets written to disk

**Flags:**
- `--docker` — Use Docker hostnames (gofr-vault:8201)
- `--vault-addr URL` — Custom Vault address
- `--policy NAME` — Token policy (default: gofr-mcp-policy)
- `--ttl DURATION` — Token TTL (default: 1h)

**See:** [lib/gofr-common/scripts/readme.md](lib/gofr-common/scripts/readme.md)

---

### auth_manager.sh
**Purpose:** Manage groups and tokens in Vault (list, create, inspect, revoke).

**Usage (requires auth_env.sh first):**
```bash
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
./lib/gofr-common/scripts/auth_manager.sh --docker groups list
./lib/gofr-common/scripts/auth_manager.sh --docker tokens list
```

**Commands:**
- `groups list` — List all groups
- `tokens list` — List all tokens
- `tokens create --groups admin --name TOKEN_NAME` — Create new token
- `tokens inspect --name TOKEN_NAME` — View token details
- `tokens revoke --name TOKEN_NAME` — Revoke token

**Flags:**
- `--docker` — Use Docker hostnames
- `--backend TYPE` — Storage backend (vault/file/memory)

**See:** [lib/gofr-common/scripts/readme.md](lib/gofr-common/scripts/readme.md)

---

### auth_manager.py
**Purpose:** Python CLI for auth operations (backend for auth_manager.sh).

**Subcommands:** `groups`, `tokens` (see auth_manager.sh for usage)

---

### bootstrap_auth.sh / bootstrap_auth.py
**Purpose:** Legacy auth bootstrap scripts (superseded by setup_approle.py in main scripts/).

---

### restart_servers.sh
**Purpose:** Restart services after config changes.

---

### run_tests.sh
**Purpose:** Run pytest suite with auth backend configured.

---

## 🚀 Bootstrap & Setup

Location: **`scripts/`**

### bootstrap.py
**Purpose:** Initialize Vault, generate secrets, provision AppRole identities.

**Usage (first run):**
```bash
uv run scripts/bootstrap.py --auto-init [--openrouter-key YOUR_KEY]
```

**Usage (existing Vault):**
```bash
uv run scripts/bootstrap.py
```

**What it does:**
1. Initializes Vault (if --auto-init)
2. Generates/stores JWT signing secret
3. Creates reserved groups (admin, public)
4. Generates bootstrap tokens (365-day)
5. Stores all secrets in Vault
6. Outputs `docker/.env` (non-secret config)

**Flags:**
- `--auto-init` — Initialize fresh Vault
- `--rotate-tokens` — Invalidate old tokens and create new ones
- `--openrouter-key KEY` — Store OpenRouter API key

**Output Files:**
- `secrets/vault_root_token` — Root token (CRITICAL)
- `secrets/vault_unseal_key` — Unseal key (CRITICAL)
- `secrets/bootstrap_tokens.json` — Admin/public tokens (CRITICAL)
- `docker/.env` — Non-secret config (safe to commit)

**See:** [scripts/readme.md](scripts/readme.md)

---

### setup_approle.py
**Purpose:** Configure AppRole auth and provision service identities.

**Usage (after bootstrap.py):**
```bash
uv run scripts/setup_approle.py
```

**What it does:**
1. Enables AppRole auth method in Vault
2. Creates/updates service policies (gofr-mcp-policy, gofr-web-policy)
3. Provisions AppRoles for services (gofr-mcp, gofr-web)
4. Generates role/secret IDs
5. Exports credentials to `secrets/service_creds/`

**Output Files:**
- `secrets/service_creds/gofr-mcp.json` — MCP AppRole credentials
- `secrets/service_creds/gofr-web.json` — Web AppRole credentials

---

### generate_envs.sh
**Purpose:** Generate port configuration and shared environment variables.

**Usage:**
```bash
./scripts/generate_envs.sh
```

**Output:**
- `lib/gofr-common/config/gofr_ports.env` — All service ports (SSOT)

---

### manage_document.sh
**Purpose:** Ingest, query, and delete documents via MCP/MCPO server.

**Usage:**
```bash
# Ingest
./scripts/manage_document.sh ingest \
  --source-guid UUID \
  --title "Title" \
  --content "Content..." \
  --token "$GOFR_IQ_ADMIN_TOKEN"

# Query
./scripts/manage_document.sh query \
  --query "search terms" \
  --n-results 10 \
  --token "$GOFR_IQ_ADMIN_TOKEN"

# Delete
./scripts/manage_document.sh delete \
  --document-guid UUID \
  --group-guid UUID \
  --confirm \
  --token "$GOFR_IQ_ADMIN_TOKEN"
```

**Flags:**
- `--docker` / `--prod` — Use production ports (default)
- `--dev` — Use development ports
- `--host HOST` — Custom MCP host
- `--port PORT` — Custom MCP port
- `--token TOKEN` — JWT auth token (required)

---

### manage_source.sh
**Purpose:** List, create, and manage document sources.

**Usage:**
```bash
./scripts/manage_source.sh list
./scripts/manage_source.sh create --name "Source Name" --token "$TOKEN"
```

---

### manage_servers.sh
**Purpose:** Health check and manage running services (start/stop/restart).

---

### run_mcp.sh / run_mcpo.sh / run_web.sh
**Purpose:** Launch individual services locally (for development).

**Usage:**
```bash
./scripts/run_mcp.sh [--no-auth]
./scripts/run_mcpo.sh
./scripts/run_web.sh
```

---

### run_tests.sh
**Purpose:** Execute full pytest suite with Vault backend.

**Usage:**
```bash
./scripts/run_tests.sh [--refresh-env]
```

**Flags:**
- `--refresh-env` — Regenerate docker/.env before testing

---

### check_version_compatibility.py
**Purpose:** Validate Python/dependency versions against requirements.

---

### export_vault_for_swarm.sh
**Purpose:** Export Vault config for Docker Swarm deployment.

---

### purge_local_data.sh
**Purpose:** Remove all local data directories (storage, auth, sessions).

**Warning:** Destructive operation; use with caution.

---

### test_env.sh / test_servers.sh
**Purpose:** Validate environment setup and service connectivity.

---

### gofriq.env / gofriq.env.example
**Purpose:** Template and instance for local API key configuration.

---

## 🐳 Docker Operations

Location: **`docker/`**

### start-prod.sh
**Purpose:** Single-command production stack startup (recommended entry point).

**Usage:**
```bash
# First time (initializes Vault)
./docker/start-prod.sh --fresh --openrouter-key sk-or-v1-YOUR-KEY

# Restart (reuses existing Vault)
./docker/start-prod.sh

# Reset all data
./docker/start-prod.sh --reset
```

**What it does:**
1. Detects host vs container environment
2. Stops existing services (preserves volumes)
3. Starts Vault
4. Runs bootstrap.py (auto-init if --fresh)
5. Runs setup_approle.py
6. Merges port config into docker/.env
7. Starts all infrastructure (Neo4j, ChromaDB)
8. Starts application services (MCP, MCPO, Web)
9. Waits for health checks

**Flags:**
- `--fresh` — Initialize Vault (use on first install)
- `--reset` — Wipe all data and volumes (nuke & pave)
- `--openrouter-key KEY` — Store OpenRouter API key in Vault

---

### run-dev.sh
**Purpose:** Start development infrastructure (databases) only.

**Usage:**
```bash
cd docker
./run-dev.sh
```

**Services Started:**
- Neo4j (port 7574 dev / 7474 prod)
- ChromaDB (port 8100 dev / 8000 prod)
- Vault (port 8200 dev / 8201 prod)

**Use when:** Running Python code locally, not containerized.

---

### build-prod.sh
**Purpose:** Build production Docker image with auto-versioning.

**Usage:**
```bash
./docker/build-prod.sh
```

**Output:** `gofr-iq-prod:VERSION` and `gofr-iq-prod:latest`

---

### build-dev.sh / build-neo4j.sh / build-chromadb.sh / build-vault.sh / build-base.sh
**Purpose:** Build individual service images.

**Usage:**
```bash
./docker/build-dev.sh     # Development environment image
./docker/build-neo4j.sh   # Neo4j with constraints/plugins
./docker/build-chromadb.sh # ChromaDB with persistence
./docker/build-vault.sh   # HashiCorp Vault
./docker/build-base.sh    # Base/common layers
```

---

### reset-prod.sh
**Purpose:** Reset production stack (alias for `start-prod.sh --reset`).

---

### manage-infra.sh
**Purpose:** Low-level infrastructure management (start/stop/status services).

---

### run-vault.sh
**Purpose:** Start Vault container only.

---

### backup.sh
**Purpose:** Backup Vault data and configurations.

---

### Entrypoint Scripts
**Purpose:** Container entry logic (executed on `docker run`).

- `entrypoint-prod.sh` — MCP/MCPO/Web startup
- `entrypoint-dev.sh` — Development environment setup
- `entrypoint-neo4j.sh` — Neo4j with constraints
- `entrypoint-chromadb.sh` — ChromaDB initialization
- `entrypoint-vault.sh` — Vault server startup

---

### Dockerfile & Config Files
**Purpose:** Container images and Vault/Docker configuration.

- `Dockerfile.prod` — Production app image
- `Dockerfile.dev` — Development environment
- `Dockerfile.neo4j` — Graph database
- `Dockerfile.chromadb` — Vector database
- `Dockerfile.vault` — HashiCorp Vault
- `docker-compose.yml` — Production stack definition
- `docker-compose-test.yml` — Test stack definition
- `vault-config.hcl` / `vault-config.json` — Vault server config

---

## 📊 Simulation & Testing

Location: **`simulation/`**

### run_simulation.py
**Purpose:** Generate synthetic client data and stories for end-to-end testing.

**Usage:**
```bash
uv run simulation/run_simulation.py --count 30 --output output_dir
```

**What it generates:**
- Synthetic APAC financial clients
- Realistic market stories with sentiment
- Client portfolios and feeds
- Ingests into running MCP server

**See:** [simulation/readme.md](../simulation/readme.md)

---

### run_simulation.sh
**Purpose:** Bash wrapper for run_simulation.py with env setup.

---

### reset_simulation_env.py / reset_simulation_env.sh
**Purpose:** Clear all simulation data from Vault/Neo4j/ChromaDB.

---

### generate_synthetic_stories.py
**Purpose:** Generate fake financial stories with NLP-generated content.

---

### generate_synthetic_clients.py
**Purpose:** Generate synthetic client profiles and portfolios.

---

### generate_client_ips.py
**Purpose:** Generate client IP addresses for geo-filtering tests.

---

### ingest_synthetic_stories.py
**Purpose:** Load synthetic stories into MCP system.

---

### load_simulation_data.py
**Purpose:** Bulk load pre-generated simulation data.

---

### query_client_feed.py
**Purpose:** Query client feed via MCP/MCPO for validation.

---

### setup_neo4j_constraints.py
**Purpose:** Create database constraints for performance and consistency.

---

### check_cache.py / check_documents.py
**Purpose:** Verify simulation data in caches (ChromaDB, Neo4j).

---

### validate_simulation.py / validate_feeds.py
**Purpose:** Validate simulation consistency and client feed correctness.

---

### client_profiler.py
**Purpose:** Analyze and profile simulated client behavior.

---

### demo_ips_filtering.py
**Purpose:** Test IP-based client filtering logic.

---

## 📁 Directory Structure

```
gofr-iq/
├── lib/gofr-common/scripts/
│   ├── auth_env.sh                    # Mint operator token
│   ├── auth_manager.sh                # Manage groups/tokens
│   ├── auth_manager.py                # Python CLI
│   ├── bootstrap_auth.sh / .py        # (Legacy)
│   ├── restart_servers.sh
│   ├── run_tests.sh
│   ├── readme.md
│   └── ...
│
├── scripts/
│   ├── bootstrap.py                   # Initialize Vault
│   ├── setup_approle.py               # Provision AppRoles
│   ├── generate_envs.sh               # Gen port config
│   ├── manage_document.sh             # Ingest/query docs
│   ├── manage_source.sh               # Manage sources
│   ├── manage_servers.sh              # Service mgmt
│   ├── run_mcp.sh / run_mcpo.sh / run_web.sh
│   ├── run_tests.sh
│   ├── check_version_compatibility.py
│   ├── export_vault_for_swarm.sh
│   ├── purge_local_data.sh
│   ├── test_env.sh / test_servers.sh
│   ├── readme.md
│   └── ...
│
├── docker/
│   ├── start-prod.sh                  # Main entry point (RECOMMENDED)
│   ├── run-dev.sh                     # Dev infrastructure
│   ├── build-prod.sh / build-*.sh     # Image builds
│   ├── reset-prod.sh
│   ├── manage-infra.sh
│   ├── run-vault.sh / backup.sh
│   ├── entrypoint-*.sh                # Container entry scripts
│   ├── Dockerfile.prod / .dev / .neo4j / .chromadb / .vault
│   ├── docker-compose.yml             # Prod stack
│   ├── docker-compose-test.yml        # Test stack
│   ├── vault-config.hcl / .json
│   ├── readme.md (implicit)
│   └── ...
│
└── simulation/
    ├── run_simulation.py              # Main simulator
    ├── run_simulation.sh              # Bash wrapper
    ├── reset_simulation_env.py / .sh
    ├── generate_synthetic_*.py        # Data generators
    ├── ingest_synthetic_stories.py
    ├── load_simulation_data.py
    ├── query_client_feed.py
    ├── setup_neo4j_constraints.py
    ├── check_*.py / validate_*.py
    ├── client_profiler.py
    ├── demo_ips_filtering.py
    ├── readme.md
    └── ...
```

---

## 🎯 Common Workflows

### New Install
```bash
cd /home/gofr/devroot/gofr-iq
./docker/start-prod.sh --fresh --openrouter-key sk-or-v1-YOUR-KEY
```

### Restart Stack
```bash
./docker/start-prod.sh
```

### View Vault Secrets
```bash
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
./lib/gofr-common/scripts/auth_manager.sh --docker groups list
./lib/gofr-common/scripts/auth_manager.sh --docker tokens list
```

### Ingest Documents
```bash
./scripts/manage_document.sh ingest \
  --source-guid SOURCE_UUID \
  --title "Document Title" \
  --content "Content..." \
  --token "$GOFR_IQ_ADMIN_TOKEN"
```

### Run Tests
```bash
./scripts/run_tests.sh
```

### Run Simulation
```bash
uv run simulation/run_simulation.py --count 50
```

---

## 📝 Notes

- **SSOT (Single Source of Truth):** Port configuration lives in `lib/gofr-common/config/gofr_ports.env`; scripts source this to avoid hardcoding.
- **Zero-Trust Bootstrap:** Secrets never cached on disk; tokens minted on-demand via `auth_env.sh`.
- **Docker-First:** Most workflows use containerized services; dev setups can use local Python + containerized infra.
- **Least-Privilege:** All service identities use AppRole with minimal-required policies.
