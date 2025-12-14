# GOFR-PLOT Architecture Analysis: MCP, MCPO & WEB Exposure Pattern

This document analyzes the mature implementation pattern used in `gofr-plot` for exposing functional capabilities across three interfaces: **MCP** (Model Context Protocol), **MCPO** (MCP-to-OpenAPI wrapper), and **WEB** (FastAPI REST API).

---

## 1. Executive Summary

`gofr-plot` implements a **layered server architecture** that exposes the same core functionality (graph rendering) through three different interfaces:

| Interface | Purpose | Transport | Port | Consumer |
|-----------|---------|-----------|------|----------|
| **MCP** | AI/LLM native protocol | Streamable HTTP | 8010 | Claude, n8n, MCP clients |
| **MCPO** | OpenAPI wrapper | HTTP REST | 8011 | OpenWebUI, REST clients |
| **WEB** | Full-featured REST API | HTTP REST | 8012 | Browsers, direct API calls |

---

## 2. Project Structure

```
gofr-plot/
├── app/
│   ├── main_mcp.py          # MCP server entry point
│   ├── main_mcpo.py         # MCPO wrapper entry point  
│   ├── main_web.py          # Web server entry point
│   ├── settings.py          # Unified configuration
│   ├── config.py            # Config class
│   │
│   ├── mcp_server/          # MCP implementation
│   │   └── mcp_server.py    # MCP tools & handlers
│   │
│   ├── mcpo_server/         # MCPO wrapper
│   │   ├── config.py        # MCPO-specific config
│   │   └── wrapper.py       # Subprocess wrapper for mcpo CLI
│   │
│   ├── web_server/          # FastAPI web server
│   │   └── web_server.py    # REST API endpoints
│   │
│   ├── auth/                # Shared authentication
│   ├── security/            # Rate limiting, auditing
│   ├── render/              # Core business logic
│   ├── storage/             # Persistence layer
│   └── ...
│
├── scripts/
│   ├── run_mcp.sh           # Start MCP server
│   ├── run_mcpo.sh          # Start MCPO wrapper
│   ├── run_web.sh           # Start Web server
│   ├── run_mcp_auth.sh      # MCP with authentication
│   ├── run_mcpo_auth.sh     # MCPO with authentication
│   ├── run_web_auth.sh      # Web with authentication
│   └── restart_servers.sh   # Orchestrated restart
│
├── docker/
│   ├── Dockerfile.dev       # Development image
│   ├── Dockerfile.prod      # Production image
│   └── docker-compose.yml   # Multi-container deployment
│
├── gofr-plot.env            # Centralized environment config
└── pyproject.toml
```

---

## 3. Layered Architecture

### 3.1 Core Business Logic (Shared)

The actual functionality is encapsulated in reusable service classes:

```python
# Core services - shared across all interfaces
from app.render import GraphRenderer
from app.validation import GraphDataValidator
from app.storage import get_storage
from app.auth import AuthService
from app.security import RateLimiter, SecurityAuditor
```

### 3.2 MCP Server Layer (`app/mcp_server/`)

The MCP server uses the official `mcp` SDK with Streamable HTTP transport:

```python
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent, ImageContent

app = Server("gofr-plot")

@app.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(name="render_graph", description="...", inputSchema={...}),
        Tool(name="list_themes", description="...", inputSchema={...}),
        Tool(name="ping", description="...", inputSchema={...}),
    ]

@app.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    # Route to appropriate handler
```

**Key Features:**

- Native MCP protocol support
- Streamable HTTP transport (modern standard)
- Tool definitions with JSON Schema
- Authentication via JWT headers
- Rate limiting per-tool

### 3.3 MCPO Wrapper Layer (`app/mcpo_server/`)

MCPO wraps the MCP server to expose tools as OpenAPI endpoints:

```python
class MCPOWrapper:
    def _build_mcpo_command(self) -> list[str]:
        cmd = [
            "uv", "tool", "run", "mcpo",
            "--port", str(self.mcpo_port),
            "--server-type", "streamable-http",
        ]
        if self.mcpo_api_key:
            cmd.extend(["--api-key", self.mcpo_api_key])
        cmd.extend(["--", f"http://{self.mcp_host}:{self.mcp_port}/mcp"])
        return cmd
```

**Key Features:**

- Spawns `mcpo` as subprocess
- Converts MCP tools → REST endpoints
- Auto-generates OpenAPI specification
- Optional API key authentication layer
- JWT token pass-through to MCP

### 3.4 Web Server Layer (`app/web_server/`)

FastAPI-based REST API with full HTTP semantics:

```python
class GraphWebServer:
    def __init__(self, auth_service=None, require_auth=True):
        self.app = FastAPI(title="gofr-plot")
        self.renderer = GraphRenderer()  # Shared service
        self._setup_routes()

    def _setup_routes(self):
        @self.app.get("/ping")
        async def ping(): ...

        @self.app.post("/render")
        async def render_graph(data: GraphParams, token: TokenInfo = Depends(auth)):
            # Same logic as MCP tool
```

**Key Features:**

- Full FastAPI capabilities
- Automatic OpenAPI docs (`/docs`, `/redoc`)
- Request/response validation (Pydantic)
- CORS middleware
- Richer error responses

---

## 4. Configuration Architecture

### 4.1 Centralized Environment File (`gofr-plot.env`)

Single source of truth sourced by all scripts:

```bash
# Environment Mode
export GOFR_PLOT_ENV="${GOFR_PLOT_ENV:-TEST}"

# Core Paths
export GOFR_PLOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export GOFR_PLOT_DATA="${GOFR_PLOT_ROOT}/${GOFR_PLOT_ENV_PATH}"
export GOFR_PLOT_LOGS="${GOFR_PLOT_ROOT}/logs"

# Server Ports
export GOFR_PLOT_MCP_PORT="${GOFR_PLOT_MCP_PORT:-8010}"
export GOFR_PLOT_MCPO_PORT="${GOFR_PLOT_MCPO_PORT:-8011}"
export GOFR_PLOT_WEB_PORT="${GOFR_PLOT_WEB_PORT:-8012}"

# Auto-Create Directories
mkdir -p "${GOFR_PLOT_AUTH}" "${GOFR_PLOT_STORAGE}" "${GOFR_PLOT_LOGS}"
```

### 4.2 Python Settings (`app/settings.py`)

Uses `gofr_common.config` for type-safe configuration:

```python
from gofr_common.config import Settings, get_settings

_ENV_PREFIX = "GOFR_PLOT"

def get_settings(reload=False, require_auth=True) -> Settings:
    return _get_settings(prefix=_ENV_PREFIX, require_auth=require_auth)
```

---

## 5. Authentication Pattern

### 5.1 Shared Auth Service

All interfaces use the same `AuthService` from `gofr_common.auth`:

```python
from gofr_common.auth import AuthService, verify_token, optional_verify_token

# Initialize once, inject everywhere
auth_service = AuthService(secret_key=jwt_secret, token_store_path=token_store)

# MCP: set_auth_service(auth_service)
# Web: GraphWebServer(auth_service=auth_service)
```

### 5.2 Auth Modes

| Mode | MCP | MCPO | WEB |
|------|-----|------|-----|
| `--no-auth` | ✅ No JWT required | ✅ Pass-through | ✅ No JWT required |
| Authenticated | JWT in header | JWT pass-through | JWT in header |
| MCPO API Key | N/A | Additional layer | N/A |

---

## 6. Docker Deployment

### 6.1 Multi-Service Compose

```yaml
services:
  mcp:
    image: gofr-plot_prod:latest
    command: python -m app.main_mcp --no-auth --host 0.0.0.0 --port 8010
    ports: ["8010:8010"]
    networks: [gofr-net]

  mcpo:
    image: gofr-plot_prod:latest
    depends_on: [mcp]
    command: python -m app.main_mcpo
    environment:
      - GOFR_PLOT_MCP_HOST=gofr-plot-mcp  # Container hostname
      - GOFR_PLOT_MCP_PORT=8010
    ports: ["8011:8011"]

  web:
    image: gofr-plot_prod:latest
    command: python -m app.main_web --no-auth --host 0.0.0.0 --port 8012
    ports: ["8012:8012"]
```

### 6.2 Key Design Decisions

1. **Single Image** - All services use the same Docker image
2. **Shared Volume** - `gofr_data` volume for persistence across services
3. **External Network** - `gofr-net` for cross-project communication
4. **Container Hostnames** - Services reference each other by container name

---

## 7. Startup Scripts Pattern

Each server has dedicated startup scripts with consistent patterns:

```bash
# run_mcp.sh, run_mcpo.sh, run_web.sh follow same structure:

# 1. Source environment
source "${PROJECT_ROOT}/gofr-plot.env"

# 2. Parse CLI args (override env vars)
while [[ $# -gt 0 ]]; do
    case $1 in
        --port) PORT="$2"; shift 2 ;;
        --no-auth) NO_AUTH="true"; shift ;;
    esac
done

# 3. Build and run command
python -m app.main_${SERVER_TYPE} \
    --host "$HOST" \
    --port "$PORT" \
    $AUTH_ARGS
```

### 7.1 Orchestrated Restart

`restart_servers.sh` restarts all servers in dependency order:

1. Kill existing processes (by port)
2. Start MCP server
3. Wait for MCP health
4. Start MCPO wrapper
5. Start Web server
6. Display status

---

## 8. Summary: Key Patterns for Replication

| Pattern | Description |
|---------|-------------|
| **Separate Entry Points** | `main_mcp.py`, `main_mcpo.py`, `main_web.py` |
| **Shared Core Logic** | Business services injected into all interfaces |
| **Shared Auth** | Single `AuthService` used across all layers |
| **Environment Config** | Single `.env` file sourced by all scripts |
| **Type-Safe Settings** | `gofr_common.config.Settings` with prefix |
| **Docker Single Image** | One image, three commands |
| **Container Networking** | External network + container hostnames |
| **Startup Scripts** | `run_*.sh` with consistent arg parsing |
| **Dependency Order** | MCP → MCPO → WEB in restart scripts |

This architecture provides:

- **Flexibility**: Choose interface per use case
- **Consistency**: Same auth, rate limits, logging everywhere
- **Maintainability**: Single codebase, shared services
- **Scalability**: Independent container scaling
