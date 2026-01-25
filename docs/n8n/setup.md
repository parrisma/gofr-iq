# n8n Setup Guide for GOFR-IQ

## Overview

n8n is integrated with GOFR-IQ to provide workflow automation capabilities. This guide covers basic setup and configuration.

## Access

- **n8n UI**: http://localhost:8084
- **Version**: 2.3.6 (latest stable)

## Initial Setup

1. Navigate to http://localhost:8084
2. Complete the initial account setup
3. Create your first workflow

## MCP Server Connection

### Configure GOFR-IQ MCP Server

1. In n8n, add an **MCP** node to your workflow
2. Configure the connection:
   - **URL**: `http://gofr-iq-mcp:8080/mcp`
   - **Transport**: HTTP/SSE (Streamable HTTP)
   - **Authentication**: See Authentication section below

### Docker Network

Both n8n and GOFR-IQ services are on the `gofr-net` Docker network:
- n8n container: `gofr-n8n`
- MCP server: `gofr-iq-mcp` (port 8080)
- MCPO server: `gofr-iq-mcpo` (port 8081)

## OpenRouter Integration

### Pre-installed Node

The `n8n-nodes-openrouter` community node is pre-installed globally in the n8n container.

### Configure OpenRouter Credential

1. Go to **Credentials** → **Add Credential**
2. Search for **OpenRouter API**
3. Enter your OpenRouter API key
4. Test the connection

### OpenRouter API Key

The OpenRouter API key is automatically loaded from Vault and available in the n8n container environment.

## Available GOFR-IQ Services

### MCP Server (Native Protocol)
- **URL**: `http://gofr-iq-mcp:8080/mcp`
- **Use for**: MCP client nodes
- **Protocol**: MCP Streamable HTTP

### MCPO Server (REST API)
- **URL**: `http://gofr-iq-mcpo:8081`
- **Use for**: Standard HTTP Request nodes
- **Protocol**: REST/HTTP wrapper around MCP tools

### OpenWebUI
- **URL**: `http://gofr-openwebui:8083`
- **Use for**: Integration with chat interface

## Example Workflows

### Basic MCP Tool Call

1. Add **MCP** node
2. Configure connection to `http://gofr-iq-mcp:8080/mcp`
3. Select a tool (e.g., `query_documents`)
4. Provide parameters
5. Execute workflow

### Document Ingestion Pipeline

```
Trigger → HTTP Request (upload) → MCP (ingest_document) → Notification
```

### Query and Process Results

```
Schedule → MCP (query_documents) → OpenRouter (summarize) → Email
```

## Troubleshooting

### Cannot Connect to MCP Server

**Check connectivity:**
```bash
docker exec gofr-n8n ping -c 2 gofr-iq-mcp
```

**Verify MCP server is running:**
```bash
docker ps | grep gofr-iq-mcp
docker logs gofr-iq-mcp
```

**Test endpoint:**
```bash
docker exec gofr-n8n wget -qO- http://gofr-iq-mcp:8080/health
```

### OpenRouter Node Not Visible

**Verify installation:**
```bash
docker exec gofr-n8n npm list -g n8n-nodes-openrouter
```

**Check node structure:**
```bash
docker exec gofr-n8n ls -la /usr/local/lib/node_modules/n8n-nodes-openrouter/dist/
```

### Restart Services

```bash
cd /home/gofr/devroot/gofr-iq
./lib/gofr-common/docker/start-tools-prod.sh
```

## Service Management

### Start Tools Stack
```bash
./lib/gofr-common/docker/start-tools-prod.sh
```

### Stop Services
```bash
docker stop gofr-n8n gofr-openwebui
```

### View Logs
```bash
docker logs -f gofr-n8n
```

### Rebuild n8n
```bash
./lib/gofr-common/docker/build-n8n-prod.sh
docker stop gofr-n8n && docker rm gofr-n8n
./lib/gofr-common/docker/start-tools-prod.sh
```

## Authentication

### MCP Authentication

GOFR-IQ MCP server uses JWT authentication. Configure authentication headers in your MCP node:

```json
{
  "Authorization": "Bearer YOUR_JWT_TOKEN"
}
```

### Development Mode (No Auth)

For development, GOFR-IQ can run without authentication:
```bash
# Set in docker-compose or environment
GOFR_IQ_AUTH_DISABLED=true
```

## Data Persistence

n8n data is persisted in Docker volumes:
- **Workflows**: `gofr-n8n-data`
- **Logs**: `gofr-n8n-logs`

## Network Architecture

```
┌─────────────┐     ┌──────────────┐
│   n8n       │────▶│  gofr-iq-mcp │
│ :8084       │     │  :8080       │
└─────────────┘     └──────────────┘
      │                     │
      │                     ▼
      │             ┌──────────────┐
      │             │  ChromaDB    │
      │             │  Neo4j       │
      │             └──────────────┘
      │
      ▼
┌─────────────┐
│ OpenRouter  │ (external)
│ API         │
└─────────────┘
```

## Further Reading

- [n8n Documentation](https://docs.n8n.io/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [GOFR-IQ Hybrid Search](../features/hybrid-search.md)
- [GOFR-IQ System Prompt](../openwebui/system_prompt.md)
