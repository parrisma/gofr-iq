# Configuration Reference

All GOFR-IQ configuration is done through environment variables with the `GOFR_IQ_` prefix.

## Configuration Files

### Primary Configuration
- **`scripts/gofriq.env`** - Centralized environment configuration
- Source this file in all scripts: `source scripts/gofriq.env`

### Environment Modes

| Mode | Data Directory | Purpose |
|------|---------------|---------|
| `PROD` | `./data` | Production deployment |
| `TEST` | `./test/data` | Automated testing (default) |
| `DEV` | `./data` | Local development |

Set via: `export GOFR_IQ_ENV=PROD` before sourcing `gofriq.env`

---

## Core Settings

### Project Directories

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_ROOT` | Auto-detected | Project root directory (auto-detected from script location) |
| `GOFR_IQ_LOGS` | `$GOFR_IQ_ROOT/logs` | Log files directory |
| `GOFR_IQ_DATA` | `$GOFR_IQ_ROOT/data` (PROD)<br>`$GOFR_IQ_ROOT/test/data` (TEST) | Data directory (mode-dependent) |
| `GOFR_IQ_STORAGE` | `$GOFR_IQ_DATA/storage` | Canonical storage directory |

**Example**:
```bash
export GOFR_IQ_ENV=PROD
source scripts/gofriq.env
echo $GOFR_IQ_STORAGE
# Output: /path/to/gofr-iq/data/storage
```

---

## Authentication Settings

### JWT Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOFR_IQ_JWT_SECRET` | ✅ Yes | ❌ None | JWT signing secret (must be set in production) |
| `GOFR_IQ_JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `GOFR_IQ_JWT_EXPIRATION` | No | `86400` | Token expiration in seconds (24 hours) |

**Security Warning**: Never commit `JWT_SECRET` to version control. Set via:
```bash
export GOFR_IQ_JWT_SECRET="your-secure-random-string-here"
```

Generate a secure secret:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Authentication Backend

| Variable | Default | Options | Description |
|----------|---------|---------|-------------|
| `GOFR_AUTH_BACKEND` | `vault` | `vault`, `file`, `memory` | Auth backend type |
| `GOFR_IQ_TOKEN_STORE` | `$GOFR_IQ_LOGS/gofriq_tokens.json` | Path | Token store for `file` backend (legacy) |

**Backend Selection**:
- **`vault`** (Production) - HashiCorp Vault server
- **`file`** (Development) - JSON file storage
- **`memory`** (Testing) - In-memory only (not persistent)

### Vault Configuration (Production)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_VAULT_URL` | `http://gofr-vault:8200` | Vault server URL |
| `GOFR_VAULT_PORT` | `8201` | Vault server port |
| `GOFR_VAULT_TOKEN` | `gofr-dev-root-token` | Vault root token (dev only) |
| `GOFR_VAULT_DEV_TOKEN` | `gofr-dev-root-token` | Development root token |
| `GOFR_VAULT_PATH_PREFIX` | `gofr-iq/auth` | Vault path prefix for auth data |
| `GOFR_VAULT_MOUNT_POINT` | `secret` | Vault KV mount point |

**Production AppRole** (set these in production, leave empty for dev):
```bash
export GOFR_VAULT_ROLE_ID="your-role-id"
export GOFR_VAULT_SECRET_ID="your-secret-id"
```

**Example Vault Setup**:
```bash
# Development (uses root token)
export GOFR_AUTH_BACKEND=vault
export GOFR_VAULT_URL=http://localhost:8200
export GOFR_VAULT_TOKEN=gofr-dev-root-token

# Production (uses AppRole)
export GOFR_AUTH_BACKEND=vault
export GOFR_VAULT_URL=https://vault.example.com
export GOFR_VAULT_ROLE_ID="your-role-id"
export GOFR_VAULT_SECRET_ID="your-secret-id"
```

---

## Server Configuration

### Network Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_HOST` | `0.0.0.0` | Server bind address (0.0.0.0 = all interfaces) |
| `GOFR_IQ_DOCKER_NETWORK` | `gofr-net` | Docker network name |

### Server Ports

| Variable | Default | Service | Description |
|----------|---------|---------|-------------|
| `GOFR_IQ_MCP_PORT` | `8080` | MCP Server | Model Context Protocol (AI assistants) |
| `GOFR_IQ_MCPO_PORT` | `8081` | MCPO Server | OpenAPI + SSE Events |
| `GOFR_IQ_WEB_PORT` | `8082` | Web Server | REST API |
| `GOFR_IQ_WEBUI_PORT` | `9095` | Web UI | Frontend interface |

**Port Allocation** (gofr-common standard):
- **gofr-iq**: 8080-8082
- **gofr-plot**: 8090-8092
- **gofr-shared-services**: 8100+

**Change Ports**:
```bash
export GOFR_IQ_MCP_PORT=9080
export GOFR_IQ_MCPO_PORT=9081
export GOFR_IQ_WEB_PORT=9082
```

---

## LLM Configuration

### OpenRouter API

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOFR_IQ_OPENROUTER_API_KEY` | ✅ Yes | ❌ None | OpenRouter API key (required for LLM features) |
| `GOFR_IQ_OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | OpenRouter API endpoint |
| `GOFR_IQ_LLM_MODEL` | No | `anthropic/claude-opus-4` | Chat model for entity extraction |
| `GOFR_IQ_EMBEDDING_MODEL` | No | `qwen/qwen3-embedding-8b` | Embedding model for vectors |
| `GOFR_IQ_LLM_MAX_RETRIES` | No | `3` | Max retry attempts for LLM API calls |
| `GOFR_IQ_LLM_TIMEOUT` | No | `60` | Request timeout in seconds |

**Get API Key**: https://openrouter.ai/keys

**Example**:
```bash
export GOFR_IQ_OPENROUTER_API_KEY="sk-or-v1-..."
export GOFR_IQ_LLM_MODEL="anthropic/claude-opus-4"
export GOFR_IQ_EMBEDDING_MODEL="qwen/qwen3-embedding-8b"
```

**Supported Models**:
- **Chat**: `anthropic/claude-opus-4`, `openai/gpt-4-turbo`, `meta-llama/llama-3.1-70b-instruct`
- **Embeddings**: `qwen/qwen3-embedding-8b`, `openai/text-embedding-3-large`

**Cost Optimization**:
- Use cheaper models for development: `openai/gpt-3.5-turbo`
- Cache embeddings to reduce API calls
- Batch extraction requests

---

## Database Configuration

### Neo4j (Graph Database)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `GOFR_IQ_NEO4J_USER` | `neo4j` | Neo4j username |
| `GOFR_IQ_NEO4J_PASSWORD` | ❌ Required | Neo4j password |
| `GOFR_IQ_NEO4J_DATABASE` | `neo4j` | Neo4j database name |

**Example**:
```bash
export GOFR_IQ_NEO4J_URI="bolt://localhost:7687"
export GOFR_IQ_NEO4J_USER="neo4j"
export GOFR_IQ_NEO4J_PASSWORD="your-secure-password"
```

**Docker Setup**:
```bash
# Set in docker-compose.yml or .env file
NEO4J_AUTH=neo4j/your-secure-password
```

### ChromaDB (Vector Database)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_CHROMA_HOST` | `None` | ChromaDB server host (None = local/ephemeral mode) |
| `GOFR_IQ_CHROMA_PORT` | `8000` | ChromaDB server port |

**Modes**:
- **HTTP Client Mode**: Set `GOFR_IQ_CHROMA_HOST` to server hostname
- **Local Mode**: Leave `GOFR_IQ_CHROMA_HOST` unset (persistent local storage)

**Example - HTTP Mode**:
```bash
export GOFR_IQ_CHROMA_HOST="localhost"
export GOFR_IQ_CHROMA_PORT=8000
```

**Example - Local Mode**:
```bash
unset GOFR_IQ_CHROMA_HOST  # Uses persistent local storage
```

**Storage Location**: `$GOFR_IQ_STORAGE/chromadb/`

---

## Feature Flags

### Document Ingestion

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_MAX_WORD_COUNT` | `20000` | Maximum words per document |
| `GOFR_IQ_DUPLICATE_THRESHOLD` | `0.95` | Similarity threshold for duplicate detection |
| `GOFR_IQ_AUTO_DETECT_LANGUAGE` | `true` | Auto-detect document language |

**Example**:
```bash
export GOFR_IQ_MAX_WORD_COUNT=50000  # Allow longer documents
export GOFR_IQ_DUPLICATE_THRESHOLD=0.90  # More aggressive deduplication
```

### Search & Ranking

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_DEFAULT_SEARCH_LIMIT` | `10` | Default number of search results |
| `GOFR_IQ_MAX_SEARCH_LIMIT` | `100` | Maximum number of search results |
| `GOFR_IQ_SEMANTIC_WEIGHT` | `0.6` | Weight for semantic similarity score |
| `GOFR_IQ_TRUST_WEIGHT` | `0.2` | Weight for source trust score |
| `GOFR_IQ_RECENCY_WEIGHT` | `0.1` | Weight for recency score |
| `GOFR_IQ_GRAPH_WEIGHT` | `0.1` | Weight for graph relationship score |

**Example**:
```bash
export GOFR_IQ_SEMANTIC_WEIGHT=0.7
export GOFR_IQ_TRUST_WEIGHT=0.15
export GOFR_IQ_RECENCY_WEIGHT=0.1
export GOFR_IQ_GRAPH_WEIGHT=0.05
```

### Client Feeds

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_FEED_DECAY_PLATINUM` | `0.05` | Hourly decay rate for PLATINUM tier |
| `GOFR_IQ_FEED_DECAY_GOLD` | `0.10` | Hourly decay rate for GOLD tier |
| `GOFR_IQ_FEED_DECAY_SILVER` | `0.15` | Hourly decay rate for SILVER tier |
| `GOFR_IQ_FEED_DECAY_BRONZE` | `0.20` | Hourly decay rate for BRONZE tier |
| `GOFR_IQ_FEED_DECAY_STANDARD` | `0.30` | Hourly decay rate for STANDARD tier |

**Example**:
```bash
export GOFR_IQ_FEED_DECAY_PLATINUM=0.03  # Slower decay for high-impact news
```

---

## Logging Configuration

### Log Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_LOG_LEVEL` | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `GOFR_IQ_LOG_FORMAT` | `json` | Log format: `json` or `text` |
| `GOFR_IQ_LOG_FILE` | `$GOFR_IQ_LOGS/gofr-iq.log` | Main log file path |
| `GOFR_IQ_AUDIT_LOG_FILE` | `$GOFR_IQ_STORAGE/audit/audit.log` | Audit log path |

**Example**:
```bash
export GOFR_IQ_LOG_LEVEL=DEBUG
export GOFR_IQ_LOG_FORMAT=text
```

**Log Locations**:
- **Application logs**: `$GOFR_IQ_LOGS/gofr-iq.log`
- **Audit logs**: `$GOFR_IQ_STORAGE/audit/{YYYY-MM-DD}/audit.log`
- **Server logs**: `$GOFR_IQ_LOGS/gofr-iq_{server}_config.json`

---

## Testing Configuration

### Test Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `GOFR_IQ_ENV` | `TEST` | Environment mode (TEST uses `test/data`) |
| `PYTEST_TIMEOUT` | `30` | Test timeout in seconds |
| `PYTEST_MARKERS` | ❌ None | pytest marker filters (e.g., `not slow`) |

**Run Tests**:
```bash
# Use TEST environment (default)
bash scripts/run_tests.sh

# Run specific test file
pytest test/test_ingest_service.py -v

# Run with markers
pytest -m "not slow" -v
```

### Test Data

Test data is isolated in `test/data/`:
```
test/data/
├── storage/
│   ├── documents/
│   ├── sources/
│   └── groups/
├── chromadb/
└── neo4j/
```

**Clean Test Data**:
```bash
rm -rf test/data/storage test/data/chromadb test/data/neo4j
```

---

## Docker Configuration

### Docker Compose Variables

Set in `.env` file or environment before running `docker compose`:

```bash
# Docker network
GOFR_IQ_DOCKER_NETWORK=gofr-net

# Volume mounts
GOFR_IQ_DATA_VOLUME=./data
GOFR_IQ_LOGS_VOLUME=./logs

# Service names
GOFR_IQ_SERVICE_NAME=gofr-iq-dev
NEO4J_SERVICE_NAME=gofr-neo4j
CHROMADB_SERVICE_NAME=gofr-chromadb
VAULT_SERVICE_NAME=gofr-vault
```

### Service Configuration

**Neo4j**:
```bash
NEO4J_AUTH=neo4j/your-password
NEO4J_PLUGINS=["apoc"]
NEO4J_ACCEPT_LICENSE_AGREEMENT=yes
```

**ChromaDB**:
```bash
CHROMA_SERVER_HOST=0.0.0.0
CHROMA_SERVER_HTTP_PORT=8000
CHROMA_PERSIST_DIRECTORY=/chroma/chroma
```

**Vault**:
```bash
VAULT_DEV_ROOT_TOKEN_ID=gofr-dev-root-token
VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200
```

---

## Production Checklist

### Required Settings

- [ ] `GOFR_IQ_ENV=PROD`
- [ ] `GOFR_IQ_JWT_SECRET` - Strong random secret
- [ ] `GOFR_IQ_OPENROUTER_API_KEY` - Valid API key
- [ ] `GOFR_IQ_NEO4J_PASSWORD` - Secure password
- [ ] `GOFR_AUTH_BACKEND=vault`
- [ ] `GOFR_VAULT_ROLE_ID` - Production AppRole
- [ ] `GOFR_VAULT_SECRET_ID` - Production AppRole secret

### Security Settings

- [ ] Change default Vault token from `gofr-dev-root-token`
- [ ] Use HTTPS for Vault (`GOFR_VAULT_URL=https://...`)
- [ ] Restrict `GOFR_IQ_HOST` to internal network (not `0.0.0.0`)
- [ ] Enable firewall rules for ports 8080-8082
- [ ] Set up log rotation for `$GOFR_IQ_LOGS`
- [ ] Configure backup for `$GOFR_IQ_STORAGE`

### Performance Tuning

```bash
# Increase LLM concurrency
export GOFR_IQ_LLM_MAX_CONCURRENT=10

# Increase search limits
export GOFR_IQ_MAX_SEARCH_LIMIT=500

# Enable caching
export GOFR_IQ_ENABLE_CACHE=true
export GOFR_IQ_CACHE_TTL=3600
```

---

## Environment Variable Loading Order

1. **System environment** (highest priority)
2. **`.env` file** (Docker Compose)
3. **`scripts/gofriq.env`** (sourced in scripts)
4. **Application defaults** (lowest priority)

**Example Override**:
```bash
# Override default port before sourcing config
export GOFR_IQ_MCP_PORT=9080
source scripts/gofriq.env
# GOFR_IQ_MCP_PORT is now 9080
```

---

## Configuration Validation

### Check Current Configuration

```bash
# Source configuration
source scripts/gofriq.env

# Check all GOFR_IQ variables
env | grep GOFR_IQ | sort

# Check authentication backend
env | grep GOFR_AUTH

# Check LLM configuration
env | grep OPENROUTER
```

### Validate Configuration

```bash
# Test JWT secret is set
python3 -c "from app.config import get_settings; get_settings()"

# Test LLM API key
python3 -c "from app.config import get_llm_settings; print(get_llm_settings().is_available)"

# Test database connections
python3 -c "from app.services.graph_index import GraphIndex; GraphIndex().health_check()"
python3 -c "from app.services.embedding_index import EmbeddingIndex; EmbeddingIndex().health_check()"
```

---

## Troubleshooting

### Common Issues

**Issue**: `JWT_SECRET not set` error
```bash
# Solution: Set JWT secret
export GOFR_IQ_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

**Issue**: `OpenRouter API key not configured` error
```bash
# Solution: Set API key
export GOFR_IQ_OPENROUTER_API_KEY="sk-or-v1-..."
```

**Issue**: `Neo4j connection failed` error
```bash
# Check Neo4j is running
docker ps | grep neo4j

# Check connection settings
echo $GOFR_IQ_NEO4J_URI
echo $GOFR_IQ_NEO4J_PASSWORD
```

**Issue**: `ChromaDB connection failed` error
```bash
# Check ChromaDB mode
echo $GOFR_IQ_CHROMA_HOST

# If using HTTP mode, check server is running
curl http://localhost:8000/api/v1/heartbeat
```

**Issue**: Test data persisting
```bash
# Clean test data
rm -rf test/data/storage test/data/chromadb test/data/neo4j
```

---

## Related Documentation

- [Quick Start Guide](quick-start.md)
- [Architecture Overview](../architecture/overview.md)
- [Authentication Architecture](../architecture/authentication.md)
- [Docker Setup Guide](../../docs/DOCKER_SETUP_GUIDE.md)
