# GOFR-IQ Project Summary

## Project Overview

**gofr-iq** is a new MCP (Model Context Protocol) server project in the GOFR family. It follows the established patterns from gofr-np, gofr-dig, gofr-doc, and gofr-plot.

## Architecture

### Shared Infrastructure (gofr-common)

All GOFR projects share a common library `gofr-common` (v1.0.0) as a git submodule at `lib/gofr-common/`. This provides:

| Module | Purpose |
|--------|---------|
| `gofr_common.auth` | JWT authentication, token management, middleware |
| `gofr_common.logger` | Logger ABC, ConsoleLogger, StructuredLogger |
| `gofr_common.config` | BaseConfig, Settings with environment prefix support |
| `gofr_common.exceptions` | GofrError hierarchy (ValidationError, SecurityError, etc.) |
| `gofr_common.mcp` | MCP response helpers (json_text, success, error) |
| `gofr_common.web` | CORS config, middleware, health endpoints, app factories |

### Project-Specific Configuration

gofr-iq uses the `GOFR_IQ` / `GOFRIQ_` environment prefix:

| Setting | Value |
|---------|-------|
| MCP Port | 8060 |
| MCPO Port | 8061 |
| Web Port | 8062 |
| Container | `gofr-iq-dev` |
| Network | `gofr-net` |

### Directory Structure

```
gofr-iq/
├── app/
│   ├── __init__.py           # v0.1.0
│   ├── config.py             # GOFR_IQ prefix, extends gofr_common.config
│   ├── auth/__init__.py      # Re-exports from gofr_common.auth
│   ├── exceptions/__init__.py # Re-exports from gofr_common.exceptions  
│   └── logger/
│       ├── __init__.py       # GOFRIQ_LOG_* env vars
│       ├── console_logger.py
│       ├── default_logger.py
│       └── structured_logger.py
├── docker/
│   ├── Dockerfile.dev        # Extends gofr-base:latest, ports 8060-8062
│   ├── build-dev.sh          # Builds gofr-iq-dev:latest
│   ├── run-dev.sh            # Runs container on gofr-net
│   └── entrypoint-dev.sh     # Installs gofr-common + project deps
├── lib/gofr-common/          # Git submodule
├── scripts/
│   ├── gofriq.env            # Centralized environment config
│   ├── restart_servers.sh    # Wrapper for shared script
│   ├── token_manager.sh      # Wrapper for shared script
│   └── run_tests.sh          # Test runner
├── test/
│   ├── conftest.py
│   ├── test_hello.py         # 4 passing tests
│   └── data/
├── data/
├── logs/
├── docs/
├── pyproject.toml
└── README.md
```

### Re-export Pattern

Projects maintain backward compatibility by re-exporting from gofr_common:

```python
# app/config.py
from gofr_common.config import Config as BaseConfig

class Config(BaseConfig):
    _env_prefix = "GOFR_IQ"

# app/auth/__init__.py
from gofr_common.auth import AuthService, TokenInfo, verify_token, ...

# app/exceptions/__init__.py
from gofr_common.exceptions import GofrError, ValidationError, ...
GofrIqError = GofrError  # Alias
```

## Development Workflow

### Build and Run Container

```bash
cd docker
./build-dev.sh    # Builds gofr-iq-dev:latest (requires gofr-base:latest)
./run-dev.sh      # Starts container on gofr-net
```

### Enter Container

```bash
docker exec -it gofr-iq-dev bash
source .venv/bin/activate
```

### Run Tests

```bash
# From host (outside container)
docker exec gofr-iq-dev bash -c 'source .venv/bin/activate && ./scripts/run_tests.sh'

# Or from inside container
./scripts/run_tests.sh
```

### Current Test Status

```
test/test_hello.py::test_hello_world PASSED
test/test_hello.py::test_app_import PASSED
test/test_hello.py::test_gofr_common_import PASSED
test/test_hello.py::test_config_import PASSED
============================== 4 passed ==============================
```

## Building Out gofr-iq

When adding MCP server functionality, follow these patterns from other projects:

1. **MCP Server**: Create `app/main_mcp.py` using `gofr_common.web.create_mcp_starlette_app()`
2. **Web Server**: Create `app/main_web.py` using `gofr_common.web.create_starlette_app()`
3. **MCP Tools**: Create `app/mcp_server/` with tool handlers
4. **Web Endpoints**: Create `app/web_server/` with FastAPI/Starlette routes

### Example MCP Tool Pattern

```python
from mcp.server import Server
from gofr_common.mcp import json_text, success, error

server = Server("gofr-iq")

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "hello":
        return json_text({"message": "Hello from gofr-iq!"})
    return error(f"Unknown tool: {name}")
```

## Git Repository

- **Remote**: `git@github.com:parrisma/gofr-iq.git`
- **Branch**: `main`

## Related Projects

| Project | Ports | Purpose |
|---------|-------|---------|
| gofr-np | 8020-8022 | Math & Financial MCP Server |
| gofr-dig | 8030-8032 | Data Integration MCP Server |
| gofr-doc | 8040-8042 | Document Processing MCP Server |
| gofr-plot | 8050-8052 | Plotting & Visualization MCP Server |
| **gofr-iq** | **8060-8062** | **New Project** |
