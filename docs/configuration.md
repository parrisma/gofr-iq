# Configuration Reference

GOFR-IQ uses a **12-Factor App** configuration strategy. All configuration is stored in environment variables, loaded primarily from `.env` files.

## 🛠️ Configuration Strategy

1.  **Shared Defaults**: Core infrastructure ports and limits are defined in `gofr-common`.
2.  **Environment Variables**: Overrides from the OS or `.env` files.
3.  **Validation**: Pydantic models validate config at startup (strict in PROD, permissive in TEST).

### Most people only need

| Variable | Why it matters | Where it comes from |
|----------|----------------|---------------------|
| `GOFR_IQ_OPENROUTER_API_KEY` | Enables LLM extraction | You provide (env or gofriq.env) |
| `GOFR_IQ_JWT_SECRET` | Signs tokens (auth) | Generated/managed by `start-prod.sh` (Vault) or set manually in dev |
| `GOFR_ENV` | Mode: `PROD`/`DEV`/`TEST` | Set in your shell before running scripts |

Everything else has sensible defaults and lives in `.env` files.

### File Locations

| File | Purpose | Managed By |
|------|---------|------------|
| `scripts/gofriq.env` | Local development overrides | **User** (Manual) |
| `docker/.env` | Runtime config for Docker; secrets merged by `start-prod.sh` | **System** (Auto-generated) |
| `lib/gofr-common/config/gofr_ports.env` | Shared port definitions (all modules) | **System** (Read-only) |

---

## 🔑 Key Environment Variables

### Core Infrastructure

| Variable | Prod Default | Description |
|----------|--------------|-------------|
| `GOFR_ENV` | `PROD` | Runtime mode: `PROD`, `DEV`, or `TEST`. |
| `GOFR_IQ_ROOT` | *(auto)* | Project root path. |
| `GOFR_IQ_LOGS` | `./logs` | Path to log directory. |

### Authentication & Secrets

**Note**: In Production, `start-prod.sh` manages these automatically via Vault.

| Variable | Description |
|----------|-------------|
| `GOFR_IQ_JWT_SECRET` | **Required**. Secret for signing auth tokens. |
| `GOFR_IQ_OPENROUTER_API_KEY` | **Required**. API Key for LLM services. |
| `GOFR_AUTH_BACKEND` | `vault` (prod) or `file` (dev). |

### Service Ports

Standard ports are defined in `lib/gofr-common/config/gofr_ports.env`.

| Service | Variable | Port |
|---------|----------|------|
| MCP | `GOFR_IQ_MCP_PORT` | 8080 |
| MCPO | `GOFR_IQ_MCPO_PORT` | 8081 |
| Web | `GOFR_IQ_WEB_PORT` | 8082 |
| Vault | `GOFR_VAULT_PORT` | 8201 |
| Chroma | `GOFR_CHROMA_PORT` | 8000 |
| Neo4j | `GOFR_NEO4J_HTTP_PORT` | 7474 |

### LLM & Model Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_LLM_MODEL` | `anthropic/claude-opus-4` | Model for extraction/chat. |
| `GOFR_IQ_EMBEDDING_MODEL` | `qwen/qwen3-embedding-8b` | Model for vector embeddings. |

---

## 🐳 Docker Configuration

When running with `docker compose`:

1.  **`start-prod.sh`** reads system environment.
2.  It merges `gofr_ports.env` and authentication secrets into `docker/.env`.
3.  Docker Compose reads `docker/.env` to configure containers.

**Manual override**: You can manually edit `docker/.env` if you need to force specific values without re-running initialization.

## 🐍 Python Configuration

In Python code, configuration is accessed via a typed singleton:

```python
from app.config import get_config

config = get_config()
print(config.llm_model)
print(config.paths.data_dir)
```

This ensures type safety and validation across the application.
