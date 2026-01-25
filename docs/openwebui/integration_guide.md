# Integrating GOFR-IQ with OpenWebUI

This guide shows how to connect OpenWebUI (an open-source ChatGPT-style interface) to GOFR-IQ's MCP server, enabling conversational access to the financial intelligence platform.

---

## Overview

**OpenWebUI** provides a chat interface for LLMs (Claude, GPT, Llama, etc.) with support for:
- Model Context Protocol (MCP) integration
- Custom system prompts
- Tool/function calling
- Multi-user management

**GOFR-IQ** exposes 15+ tools via MCP for:
- Document ingestion and search
- Client portfolio management
- Personalized news feeds
- Knowledge graph exploration

Together, they enable natural language queries like:
- *"What news affects my tech holdings?"*
- *"Add NVDA to the hedge fund portfolio"*
- *"Who supplies Apple?"*

---

## Architecture

```
┌─────────────┐          ┌──────────────┐          ┌─────────────┐
│  OpenWebUI  │  HTTP    │   GOFR-IQ    │  Bolt    │   Neo4j     │
│   (Port     │────────▶│  MCPO Server │─────────▶│  (Graph)    │
│    8083)    │          │  (Port 8081) │          └─────────────┘
└─────────────┘          └──────────────┘
      │                         │                   ┌─────────────┐
      │                         └──────────────────▶│  ChromaDB   │
      │                                             │  (Vector)   │
      │                                             └─────────────┘
      │                         ┌──────────────┐
      └────────────────────────▶│   Vault      │
         (JWT Token)            │  (Auth)      │
                                └──────────────┘

Note: Services communicate via Docker network (gofr-net)
```

---

## Prerequisites

1. **GOFR-IQ Running**: `./docker/start-prod.sh`
2. **OpenWebUI Running**: `./lib/gofr-common/docker/start-tools-prod.sh`
3. **Network Access**: Both services are on the `gofr-net` Docker network

---

## Step-by-Step Setup

### 1. Start GOFR-IQ and OpenWebUI
```bash
cd /home/gofr/devroot/gofr-iq

# Start GOFR-IQ core services (Neo4j, ChromaDB, Vault, MCPO)
./docker/start-prod.sh

# Start OpenWebUI tools stack
./lib/gofr-common/docker/start-tools-prod.sh

# Verify MCPO server is running
curl http://localhost:8081/health
# Should return: {"status": "healthy"}

# Verify OpenWebUI is running
curl http://localhost:8083
# Should return: HTML page
```

**Note**: OpenWebUI is managed by the GOFR tools stack and runs on port 8083 by default.

### 2. Get Authentication Token
GOFR-IQ uses JWT tokens for access control. Get a token for the group you want to access:

```bash
# Option A: Use bootstrap token (pre-generated for admins)
cat config/generated/bootstrap_tokens.json | jq -r '.admin_token'

# Option B: Generate a new token via Vault
source <(./lib/gofr-common/scripts/auth_env.sh --docker)
./lib/gofr-common/scripts/auth_manager.sh --docker tokens create \
  --groups apac-sales,reuters-feed \
  --ttl 86400
```

Copy the token - you'll need it in Step 4.

### 3. Configure OpenWebUI

#### A. Add System Prompt
1. Open OpenWebUI: `http://localhost:3000`
2. Navigate to **Settings** (gear icon) → **System Prompt**
3. Paste the system prompt from [system_prompt.md](system_prompt.md)

**Quick Copy**:
```bash
# Copy system prompt to clipboard
cat docs/openwebui/system_prompt.md | grep -A 100 "## System Prompt" | head -n 80
```

#### B. Configure MCP Connection
1. Go to **Settings** → **Connections** → **MCP Servers**
2. Click **Add Server**
3. Configure:
   - **Name**: `gofr-iq`
   - **URL**: `http://gofr-mcpo:8081` (internal Docker network)
   - **Type**: `HTTP`
   - **Authentication**: `Bearer Token`
   - **Token**: (Paste JWT token from Step 2)

4. Click **Save** and **Test Connection**
   - Should show: ✅ Connected - 15 tools discovered

**Note**: OpenWebUI and GOFR-IQ run on the same Docker network (`gofr-net`), so use container name `gofr-mcpo` instead of `localhost` or `host.docker.internal`.

### 4. Select LLM Model
OpenWebUI supports multiple LLM backends:

- **OpenAI**: Configure API key in Settings → Models
- **Ollama**: Local models (llama3, mistral, etc.) - install separately
- **Claude**: Via API proxy or direct integration

**Recommended for GOFR-IQ**: Claude Sonnet 3.5 or GPT-4 (best tool-calling performance)

### 5. Test Integration
Open OpenWebUI at `http://localhost:8083` and start a new chat:

```
User: "What MCP tools are available?"
Assistant: [Lists 15 GOFR-IQ tools with descriptions]

User: "List all companies in the system"
Assistant: [Calls list_companies tool]
Returns: GigaTech Inc. (GTX), OmniCorp Global (OMNI), Quantum Compute (QNTM)...

User: "What news affects clients holding tech stocks?"
Assistant: [Calls list_clients, filters tech holders, calls get_client_feed]
Returns personalized feed with recent stories about QNTM, GTX, NXS...
```

---

## Usage Patterns

### Query Documents
```
"Find all documents mentioning supply chain issues"
→ Calls query_documents with semantic search
```

### Explore Graph
```
"What companies compete with Apple?"
→ Calls get_company_relationships
→ Returns: Samsung, Google, Microsoft
```

### Manage Client Portfolios
```
"Add Tesla (5% weight) to the hedge fund portfolio"
→ Calls list_clients to find hedge fund
→ Calls add_to_portfolio with ticker=TSLA, weight=5.0
```

### Get Personalized Feed
```
"Show me news for conservative pension fund clients"
→ Calls list_clients, filters by type=PENSION
→ Calls get_client_feed with high trust threshold
→ Returns filtered news (only PLATINUM/GOLD tier)
```

---

## Troubleshooting

### "Connection Refused" Error
**Symptom**: OpenWebUI cannot reach MCP server

**Fix**:
```bash
# OpenWebUI and GOFR-IQ are on the same Docker network (gofr-net)
# Use container name: http://gofr-mcpo:8081
# NOT: http://localhost:8081 or http://host.docker.internal:8081

# Test from OpenWebUI container
docker exec -it gofr-openwebui curl http://gofr-mcpo:8081/health

# Verify both containers are on gofr-net
docker network inspect gofr-net | grep -E 'gofr-openwebui|gofr-mcpo'
```

### "Authentication Failed" Error
**Symptom**: 401 Unauthorized responses

**Fix**:
```bash
# Verify token is valid
export TOKEN="<your-jwt-token>"
curl -H "Authorization: Bearer $TOKEN" http://localhost:8081/health

# If expired, generate new token (see Step 2)
```

### "No Tools Found" Error
**Symptom**: MCP connection succeeds but no tools discovered

**Fix**:
1. Ensure GOFR-IQ MCPO server is running (not just Web API)
2. Check MCPO endpoint: `curl http://localhost:8081/tools/list`
3. Restart OpenWebUI: `docker restart gofr-openwebui`

### LLM Not Using Tools
**Symptom**: LLM responds with generic answers instead of calling tools

**Fix**:
1. Verify system prompt is loaded (see Step 3A)
2. Use a model with strong tool-calling (Claude Sonnet, GPT-4)
3. Try explicit prompt: *"Use MCP tools to answer this"*

---

## Advanced Configuration

### Multi-User Setup
Create separate tokens for different user groups:

```bash
# Sales team token (read-only)
./auth_manager.sh tokens create --groups apac-sales,us-sales --scopes read

# Trading desk token (write access)
./auth_manager.sh tokens create --groups trading-desk --scopes read,write

# Admin token (full access)
./auth_manager.sh tokens create --groups admin --scopes read,write,admin
```

Configure users in OpenWebUI → Admin → Users, assign different tokens per role.

### Custom Tool Aliases
OpenWebUI allows renaming tools for clarity:

```yaml
# In OpenWebUI MCP config
tool_aliases:
  get_client_feed: "Get Personalized News Feed"
  query_documents: "Search Documents"
  add_to_portfolio: "Add Stock to Portfolio"
```

### Rate Limiting
Protect GOFR-IQ from excessive queries:

```python
# In OpenWebUI backend config
MCP_RATE_LIMIT = "10 per minute"
MCP_BURST = 3
```

---

## Production Deployment

### SSL/TLS
Use reverse proxy (nginx) for HTTPS:

```nginx
server {
    listen 443 ssl;
    server_name openwebui.example.com;
    
    location /mcp/ {
        proxy_pass http://gofr-iq-mcp:8080/;
        proxy_set_header Authorization $http_authorization;
    }
}
```

### Monitoring
Track MCP usage via logs:

```bash
# GOFR-IQ access logs
tail -f data/logs/mcp.log | grep "tool_call"

# OpenWebUI metrics
docker logs openwebui | grep "mcp_request"
```

### Backup
Token rotation schedule:

```bash
# Weekly token refresh (cron job)
0 0 * * 0 /path/to/rotate_tokens.sh
```

---

## Resources

- **System Prompt**: [system_prompt.md](system_prompt.md) - LLM instructions for GOFR-IQ
- **MCP Tools Reference**: See `app/tools/` directory for tool implementations
- **OpenWebUI Docs**: [docs.openwebui.com](https://docs.openwebui.com)
- **GOFR-IQ API**: [docs/features/functional_summary.md](../features/functional_summary.md)

---

## Example Conversation

```
User: I'm a trader managing hedge fund portfolios. What can you help me with?