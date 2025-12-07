# GOFR-IQ: MCP Server Template

GOFR-IQ is a Model Context Protocol (MCP) server project. This is a clean starting point for building MCP-based services.

## 🚀 Features

- **gofr-common Integration**: Uses shared authentication, logging, config, and web modules
- **Docker Development**: Containerized development environment
- **Standard Ports**: 8060 (MCP), 8061 (MCPO), 8062 (Web)

## 🏗️ Project Structure

```
gofr-iq/
├── app/
│   ├── auth/           # Re-exports from gofr_common.auth
│   ├── exceptions/     # Re-exports from gofr_common.exceptions
│   ├── logger/         # Re-exports from gofr_common.logger
│   └── config.py       # Project config with GOFR_IQ prefix
├── docker/
│   ├── Dockerfile.dev
│   ├── build-dev.sh
│   ├── run-dev.sh
│   └── entrypoint-dev.sh
├── lib/
│   └── gofr-common/    # Git submodule
├── scripts/
│   ├── gofriq.env
│   ├── restart_servers.sh
│   └── token_manager.sh
└── test/
    └── test_hello.py
```

## 🛠️ Getting Started

### Prerequisites

- Docker
- gofr-base:latest image (from gofr-common)

### Build and Run

```bash
cd docker
./build-dev.sh
./run-dev.sh
```

### Enter Container

```bash
docker exec -it gofr-iq-dev bash
source .venv/bin/activate
```

### Run Tests

```bash
pytest test/
```

## 📦 Dependencies

Core dependencies come from `gofr-common`:
- mcp, pydantic, fastapi, uvicorn, starlette
- PyJWT, httpx, mcpo

## 📝 License

MIT
