# GOFR-IQ Copilot Instructions

## ⚠️ CRITICAL: Dev Container Environment

**ALL code runs inside Docker.** Never use `localhost` - use container hostnames:

| Service | Hostname | Port |
|---------|----------|------|
| Vault | `gofr-vault` | 8201 |
| Neo4j | `gofr-neo4j` | 7687 |
| ChromaDB | `gofr-chroma` | 8000 |
| MCP | `gofr-iq-mcp` | 8080 |
| MCPO | `gofr-iq-mcpo` | 8081 |
| Web | `gofr-iq-web` | 8082 |

**Always use `--docker` flag** with management scripts.

---

## Project Layout

```
app/              # FastAPI servers (MCP, MCPO, Web)
lib/gofr-common/  # Shared auth, config, services
scripts/          # Management CLI tools
docker/           # Compose files, Dockerfiles
secrets/          # Git-ignored credentials (generated)
config/           # SSOT configuration
data/             # Runtime data
simulation/       # Test data generation
```

---

## Authentication System

### Key Concepts

- **JWT-based** with multi-group support (`groups: ["us-sales", "reporting"]`)
- **Vault backend** stores metadata only - **JWT strings are NOT stored**
- **Soft-delete**: tokens revoked, groups made defunct (audit trail preserved)
- **Token validation**: JWT decoded → `jti` (UUID) extracted → Vault lookup

### Storage Locations

| Location | Contents |
|----------|----------|
| `secrets/vault_root_token` | Vault root access |
| `secrets/bootstrap_tokens.json` | Initial admin/public JWTs |
| `secret/gofr/auth/tokens/{uuid}` | Token metadata (Vault) |
| `secret/gofr/auth/groups/{uuid}` | Group metadata (Vault) |
| `secret/gofr/config/jwt-signing-secret` | JWT signing key (Vault) |

### ⚠️ JWT Strings Must Be Captured at Creation

JWTs are returned **once** when created. To get a usable token:

```bash
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
TOKEN=$(./lib/gofr-common/scripts/auth_manager.sh --docker tokens create \
  --groups us-sales --name my-token --expires 31536000)
echo "$TOKEN" > my-token.jwt  # Save it!
```

`tokens list` shows metadata only, not JWT strings.

---

## Commands

### Services
```bash
./scripts/start-prod.sh          # Start/restart production
./scripts/start-prod.sh --fresh  # First-time setup
./docker/start-tools-prod.sh    # n8n, OpenWebUI
./scripts/run_tests.sh          # Run tests
```

### Auth Management
```bash
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
./lib/gofr-common/scripts/auth_manager.sh --docker groups list
./lib/gofr-common/scripts/auth_manager.sh --docker tokens list
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups GROUP --name NAME
```

### Documents
```bash
./scripts/manage_document.sh ingest --source-guid UUID --title "..." --content "..." --token $TOKEN
./scripts/manage_document.sh query --query "search" --token $TOKEN
./scripts/manage_source.sh list
```

### Simulation
```bash
uv run simulation/run_simulation.py --count 50
```

---

## Environment Variables

| Variable | Value (in container) |
|----------|---------------------|
| `GOFR_VAULT_URL` | `http://gofr-vault:8201` |
| `GOFR_AUTH_BACKEND` | `vault` / `file` / `memory` |
| `GOFR_IQ_JWT_SECRET` | JWT signing secret |
| `GOFR_IQ_NEO4J_URI` | `bolt://gofr-neo4j:7687` |
| `GOFR_IQ_CHROMA_HOST` | `gofr-chroma` |

---

## Code Patterns

```python
# Imports
from gofr_common.auth import AuthService, create_stores_from_env
from gofr_common.config import InfrastructureConfig
from app.services.document_service import DocumentService
from app.logger import StructuredLogger
```

- Type hints required
- Async/await for I/O
- `StructuredLogger` for logging
- Env prefix: `GOFR_IQ_*` (project), `GOFR_*` (shared)

---

## Stack

FastAPI • Vault • Neo4j • ChromaDB • Pydantic • structlog • pytest  
MCP Protocol (JSON-RPC 2.0) • Cypher • OpenRouter/OpenAI
