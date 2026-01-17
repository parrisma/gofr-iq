# Service Compatibility Matrix

This document maps external service versions to their corresponding Python library versions.
All versions must match exactly. See [Version Policy](docs/development.md#version-policy--service-compatibility) for policy details.

**Last Updated:** 2024-12-20

---

## External Services

| Service | Docker Image | Version | Python Library | Library Version | Notes |
|---------|--------------|---------|----------------|-----------------|-------|
| ChromaDB | `chromadb/chroma` | 0.5.23 | `chromadb` | 0.5.23 | Client/server versions MUST match exactly |
| Neo4j | `neo4j` | 5.26.18-community | `neo4j` | 6.0.3 | Neo4j driver 6.x supports server 5.x |
| Vault | `hashicorp/vault` | 1.15.6 | `hvac` | 2.4.0 | hvac 2.x supports Vault 1.x |

---

## Python Dependencies (gofr-iq)

| Library | Version | Purpose |
|---------|---------|---------|
| `chromadb` | 0.5.23 | Vector database client |
| `neo4j` | 6.0.3 | Graph database driver |
| `hvac` | 2.4.0 | HashiCorp Vault client |
| `lingua-language-detector` | 2.1.1 | Language detection |

---

## Python Dependencies (gofr-common)

| Library | Version | Purpose |
|---------|---------|---------|
| `mcp` | 1.23.1 | Model Context Protocol |
| `pydantic` | 2.12.5 | Data validation |
| `fastapi` | 0.115.9 | Web framework |
| `uvicorn` | 0.38.0 | ASGI server |
| `starlette` | 0.45.3 | ASGI toolkit |
| `sse-starlette` | 3.0.3 | Server-sent events |
| `PyJWT` | 2.10.1 | JWT authentication |
| `httpx` | 0.28.1 | HTTP client |
| `mcpo` | 0.0.19 | MCP OpenAPI wrapper |
| `pyright` | 1.1.407 | Type checker |

---

## Dev Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| `pytest` | 9.0.2 | Test framework |
| `pytest-asyncio` | 1.3.0 | Async test support |
| `pytest-cov` | 7.0.0 | Coverage reporting |
| `black` | 25.11.0 | Code formatter |
| `ruff` | 0.14.8 | Linter |
| `bandit` | 1.9.2 | Security linter |

---

## Base Images

| Image | Version | Used In |
|-------|---------|---------|
| `python` | 3.11.11-slim | Dockerfile.prod |
| `hashicorp/vault` | 1.15.6 | Dockerfile.vault, run_tests.sh |
| `chromadb/chroma` | 0.5.23 | Dockerfile.chromadb |
| `neo4j` | 5.26.18-community | Dockerfile.neo4j |
