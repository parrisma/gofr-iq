# OpenWebUI Integration

> Connect GOFR-IQ's MCP server to OpenWebUI for conversational access to financial intelligence tools.

---

## Quick Links

- **[Integration Guide](integration_guide.md)** — Complete setup instructions (start here)
- **[System Prompt](system_prompt.md)** — LLM instructions for GOFR-IQ tools

---

## What's Inside

This directory contains documentation for integrating GOFR-IQ with OpenWebUI and other LLM chat interfaces that support Model Context Protocol (MCP).

### Files

1. **integration_guide.md**
   - Architecture overview
   - Step-by-step setup
   - Authentication (JWT tokens)
   - Testing and troubleshooting
   - Production deployment tips

2. **system_prompt.md**
   - Ready-to-paste system prompt for LLMs
   - Tool categories and descriptions
   - Example workflows
   - Token management instructions

---

## Quickstart (5 Minutes)

```bash
# 1. Start GOFR-IQ
./docker/start-prod.sh

# 2. Start OpenWebUI tools stack
./lib/gofr-common/docker/start-tools-prod.sh

# 3. Get authentication token
cat config/generated/bootstrap_tokens.json | jq -r '.admin_token'

# 4. Configure in OpenWebUI (http://localhost:8083)
# - Settings → Connections → Add MCP Server
# - URL: http://gofr-mcpo:8081
# - Token: (paste from step 3)
# - System Prompt: (paste from system_prompt.md)

# 5. Test
# Chat: "What MCP tools are available?"
```

**Full details**: [integration_guide.md](integration_guide.md)

---

## Supported Interfaces

While this documentation focuses on OpenWebUI, the system prompt and MCP configuration work with any compatible interface:

- **OpenWebUI** — Self-hosted ChatGPT-style UI
- **Claude Desktop** — Via MCP configuration file
- **Custom UIs** — Any client supporting MCP HTTP protocol
- **API Integration** — Direct REST calls to `http://localhost:8080`

---

## Architecture

```
┌─────────────────┐
│   LLM Interface │  (OpenWebUI, Claude Desktop, etc.)
│   - Chat UI     │
│   - System      │
│     Prompt      │
└────────┬────────┘
         │
         │ HTTP/MCP (gofr-net)
         ▼
┌─────────────────┐
│   GOFR-IQ MCPO  │
│   Server        │
│   (Port 8081)   │
│                 │
│   15+ Tools:    │
│   - Documents   │
│   - Clients     │
│   - Portfolio   │
│   - Graph       │
│   - Feeds       │
└────────┬────────┘
         │
         │ Bolt/HTTP
         ▼
┌─────────────────┐       ┌──────────────┐
│   Neo4j Graph   │       │  ChromaDB    │
│   Database      │       │  Vector DB   │
└─────────────────┘       └──────────────┘
```

---

## Key Concepts

### JWT Authentication
GOFR-IQ uses JWT tokens for access control. Tokens encode:
- **Groups**: Which datasets the user can access (e.g., `apac-sales`, `reuters-feed`)
- **Scopes**: Read/write permissions
- **TTL**: Token expiration time

See [integration_guide.md → Step 2](integration_guide.md#2-get-authentication-token) for token generation.

### MCP Tools
GOFR-IQ exposes 15+ tools via Model Context Protocol:

| Category | Tools |
|----------|-------|
| **Ingestion** | ingest_document |
| **Query** | query_documents |
| **Client Management** | list_clients, add_client, assign_group |
| **Portfolio** | list_portfolio, add_to_portfolio, remove_from_portfolio |
| **Watchlist** | list_watchlist, add_to_watchlist, remove_from_watchlist |
| **Feeds** | get_client_feed |
| **Graph** | list_companies, get_company_relationships, traverse_supply_chain |
| **Sources** | get_sources, register_source |

See [system_prompt.md → Tool Categories](system_prompt.md#tool-categories) for full descriptions.

### System Prompt
The system prompt teaches the LLM:
1. How to discover available tools
2. When to call specific tools (e.g., portfolio vs watchlist)
3. How to chain tools for complex queries
4. Data format expectations (ticker symbols, scores, etc.)

**Usage**: Copy the prompt from [system_prompt.md](system_prompt.md) into OpenWebUI Settings → System Prompt.

---

## Common Workflows

### 1. Query Documents
```
User: "Find all documents about semiconductor shortages"
→ LLM calls query_documents(query="semiconductor shortages")
→ Returns: 12 documents with titles, scores, snippets
```

### 2. Personalized Feed
```
User: "What news should I show to conservative pension funds?"
→ LLM calls list_clients(client_type="PENSION")
→ LLM calls get_client_feed(client_id=..., trust_threshold="HIGH")
→ Returns: Filtered feed (only PLATINUM/GOLD tier sources)
```

### 3. Portfolio Management
```
User: "Add Microsoft to hedge fund portfolios at 3% weight"
→ LLM calls list_clients(client_type="HEDGE_FUND")
→ LLM calls add_to_portfolio(client_id=..., ticker="MSFT", weight=3.0)
→ Confirms: Added MSFT (3.0%) to client XYZ
```

### 4. Graph Exploration
```
User: "What companies does Tesla compete with?"
→ LLM calls get_company_relationships(company="Tesla", rel_type="COMPETES_WITH")
→ Returns: [Ford, GM, Rivian, BYD, Volkswagen]
```

---

## Troubleshooting

### \"Connection Refused\" Error
**Error**: Connection refused or timeout

**Check**:
```bash
# Verify GOFR-IQ MCPO is running
curl http://localhost:8081/health

# Verify OpenWebUI is running
curl http://localhost:8083

# Ensure both are on gofr-net
docker network inspect gofr-net | grep -E 'gofr-openwebui|gofr-mcpo'

# In OpenWebUI config, use container name:
# http://gofr-mcpo:8081
```

### Authentication Errors
**Error**: 401 Unauthorized

**Fix**:
```bash
# Test token manually
export TOKEN="<your-jwt-token>"
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8081/tools/list

# If expired, generate new token
cat config/generated/bootstrap_tokens.json | jq -r '.admin_token'
```

### LLM Not Using Tools
**Problem**: LLM provides generic answers instead of calling tools

**Fix**:
1. Ensure system prompt is loaded (Settings → System Prompt)
2. Use a model with strong tool-calling (Claude Sonnet, GPT-4)
3. Try explicit prompt: *"Use MCP tools to answer this"*

**Full troubleshooting guide**: [integration_guide.md → Troubleshooting](integration_guide.md#troubleshooting)

---

## Next Steps

1. **Setup**: Follow [integration_guide.md](integration_guide.md) to configure OpenWebUI
2. **Test**: Try example queries from [system_prompt.md → Example Interactions](system_prompt.md#example-interactions)
3. **Customize**: Adjust system prompt for your use case
4. **Deploy**: See [integration_guide.md → Production Deployment](integration_guide.md#production-deployment) for SSL, monitoring, backups

---

## Resources

- **GOFR-IQ Docs**: [../features/functional_summary.md](../features/functional_summary.md)
- **Neo4j Query Guide**: [../../simulation/docs/neo4j_queries.md](../../simulation/docs/neo4j_queries.md)
- **OpenWebUI Docs**: [docs.openwebui.com](https://docs.openwebui.com)
- **MCP Protocol**: [modelcontextprotocol.io](https://modelcontextprotocol.io)

---

**Questions?** See [integration_guide.md](integration_guide.md) for detailed answers.
