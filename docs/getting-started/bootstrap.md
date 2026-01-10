# GOFR-IQ Bootstrap Guide

Complete guide to bootstrap GOFR-IQ from scratch, creating groups, sources, and ingesting your first document.

## Prerequisites

```bash
cd /home/gofr/devroot/gofr-iq
source lib/gofr-common/config/gofr_ports.sh
```

---

## Step 1: Start Infrastructure & Services

### 1.1 Start Docker Compose Stack

```bash
cd /home/gofr/devroot/gofr-iq/docker
./start-swarm.sh
```

**Verify all services are healthy:**

```bash
docker compose ps
```

Expected output: 6 services running and healthy:
- `gofr-vault` - Authentication backend (port 8201)
- `gofr-neo4j` - Graph database (ports 7474, 7687)
- `gofr-chromadb` - Vector database (port 8000)
- `gofr-iq-mcp` - MCP server (port 8080)
- `gofr-iq-mcpo` - MCPO API wrapper (port 8081)
- `gofr-iq-web` - Web health check (port 8082)

---

## Step 2: Bootstrap Authentication Groups

### 2.1 Create Reserved Groups & Generate Tokens

```bash
cd /home/gofr/devroot/gofr-iq

# Generate bootstrap tokens and save to environment file
./scripts/bootstrap_groups.sh > tokens.env

# Load tokens into current shell
source tokens.env

# Verify tokens were created
echo "Public Token: ${GOFR_IQ_PUBLIC_TOKEN:0:50}..."
echo "Admin Token: ${GOFR_IQ_ADMIN_TOKEN:0:50}..."
```

**What this does:**
- Creates `public` group with automatically generated UUID
- Creates `admin` group with automatically generated UUID
- Generates 10-year JWT tokens for each group
- Stores groups in Vault at `secret/gofr-iq/auth/groups/`

### 2.2 Verify Groups Exist in Vault

```bash
docker exec gofr-vault vault kv get -format=json secret/gofr-iq/auth/groups/_index/names | python3 -m json.tool
```

Expected output:
```json
{
  "data": {
    "data": {
      "admin": "a14c685b-1ee3-4cc2-ba73-de24f5c58b29",
      "public": "0a966f51-f9a2-4d5e-affc-ca4a6d184e84"
    }
  }
}
```

---

## Step 3: Get Group UUIDs

The MCP tools expect group UUIDs, not names. Extract and save them:

```bash
# Get public group UUID
PUBLIC_GROUP_UUID=$(docker exec gofr-vault vault kv get -format=json secret/gofr-iq/auth/groups/_index/names 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin)['data']['data']['public'])")

# Get admin group UUID  
ADMIN_GROUP_UUID=$(docker exec gofr-vault vault kv get -format=json secret/gofr-iq/auth/groups/_index/names 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin)['data']['data']['admin'])")

echo "Public Group UUID: $PUBLIC_GROUP_UUID"
echo "Admin Group UUID: $ADMIN_GROUP_UUID"

# Save for later use
export PUBLIC_GROUP_UUID
export ADMIN_GROUP_UUID
```

---

## Step 4: Create a News Source

### 4.1 Create Reuters Source

Use the `manage_source.sh` script to create a news source:

```bash
# Create source with public group
./scripts/manage_source.sh create \
  --name "Reuters" \
  --url "https://www.reuters.com" \
  --description "International news agency" \
  --source-type "news_agency" \
  --group-guid "${PUBLIC_GROUP_UUID}" \
  --host gofr-iq-mcp
```

**Expected output:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [{
      "type": "text",
      "text": "{\"status\":\"success\",\"data\":{\"guid\":\"<source-uuid>\",\"name\":\"Reuters\",\"url\":\"https://www.reuters.com\"}}"
    }]
  }
}
```

### 4.2 List Sources and Save GUID

Verify the source was created and extract its GUID:

```bash
# List all sources
./scripts/manage_source.sh list --host gofr-iq-mcp

# Extract Reuters source GUID (copy from output above)
SOURCE_GUID="<paste-reuters-guid-here>"
export SOURCE_GUID
echo "Source GUID: $SOURCE_GUID"
```

---

## Step 5: Ingest a Document

### 5.1 Create MCP Helper for Document Operations

For document ingestion and queries, create a simple MCP helper:

```bash
cat > /tmp/mcp_call.sh << 'EOF'
#!/bin/bash
HOST=${1:-gofr-iq-mcp}
PORT=${2:-8080}
TOOL=${3}
ARGS=${4:-'{}'}

SESSION_ID=$(curl -s -D - -X POST "http://${HOST}:${PORT}/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"cli","version":"1.0"}}}' \
  2>/dev/null | grep -i "mcp-session-id:" | cut -d: -f2 | tr -d ' \r')

curl -s -X POST "http://${HOST}:${PORT}/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: ${SESSION_ID}" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"${TOOL}\",\"arguments\":${ARGS}}}" \
  | grep "^data:" | sed 's/^data: //' | python3 -m json.tool
EOF

chmod +x /tmp/mcp_call.sh
```

### 5.2 Ingest Document

```bash
/tmp/mcp_call.sh gofr-iq-mcp 8080 ingest_document "{
  \"title\": \"Global Markets Update\",
  \"content\": \"Global stock markets showed mixed results today as investors digested the latest economic data. The S&P 500 rose 0.5% while European markets remained flat. Technology stocks led the gains with strong earnings reports from major companies. Analysts expect continued volatility as central banks assess their monetary policies.\",
  \"source_guid\": \"${SOURCE_GUID}\",
  \"group_guid\": \"${PUBLIC_GROUP_UUID}\",
  \"language\": \"en\",
  \"metadata\": {
    \"author\": \"Reuters Staff\",
    \"published_date\": \"2026-01-08\"
  }
}"
```

**Expected output:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [{
      "type": "text",
      "text": "{\"status\":\"success\",\"data\":{\"guid\":\"<document-uuid>\",\"status\":\"success\",\"language\":\"en\",\"word_count\":52,\"created_at\":\"2026-01-08T13:30:00Z\"}}"
    }]
  }
}
```

### 5.3 Save Document GUID

```bash
DOCUMENT_GUID="<paste-document-guid-from-above>"
export DOCUMENT_GUID
echo "Document GUID: $DOCUMENT_GUID"
```

---

## Step 6: Verify Document Was Ingested

### 6.1 Query Documents

Search for documents containing "global markets":

```bash
/tmp/mcp_call.sh gofr-iq-mcp 8080 query_documents "{
  \"query\": \"global markets\",
  \"group_guid\": \"${PUBLIC_GROUP_UUID}\",
  \"limit\": 5
}"
```

### 6.2 Get Specific Document

Retrieve a document by its GUID:

```bash
/tmp/mcp_call.sh gofr-iq-mcp 8080 get_document "{
  \"guid\": \"${DOCUMENT_GUID}\",
  \"group_guid\": \"${PUBLIC_GROUP_UUID}\"
}"
```

### 6.3 List All Sources

Verify your source was created:

```bash
./scripts/manage_source.sh list --host gofr-iq-mcp
```

---

## Step 7: Health Check

Verify all systems are operational:

```bash
/tmp/mcp_call.sh gofr-iq-mcp 8080 health_check "{}"
```

**Expected output:**
```json
{
  "status": "healthy",
  "components": {
    "neo4j": "connected",
    "chromadb": "connected",
    "llm_api": "available"
  }
}
```

---

## Complete Bootstrap Script

Here's everything combined into one automated script:

```bash
#!/bin/bash
# Complete GOFR-IQ Bootstrap Script
# Usage: ./bootstrap_complete.sh

set -e
cd /home/gofr/devroot/gofr-iq

echo "=== GOFR-IQ Complete Bootstrap ==="
echo ""

echo "Step 1: Loading Port Configuration..."
source lib/gofr-common/config/gofr_ports.sh
echo "✓ Port configuration loaded"
echo ""

echo "Step 2: Starting Services..."
cd docker
./start-swarm.sh
cd ..
echo "✓ Services started"
echo ""

echo "Step 3: Waiting for services to be healthy (30s)..."
sleep 30
echo ""

echo "Step 4: Bootstrap Authentication..."
./scripts/bootstrap_groups.sh > tokens.env
source tokens.env
echo "✓ Tokens created and loaded"
echo ""

echo "Step 5: Extracting Group UUIDs..."
PUBLIC_GROUP_UUID=$(docker exec gofr-vault vault kv get -format=json secret/gofr-iq/auth/groups/_index/names 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin)['data']['data']['public'])")
ADMIN_GROUP_UUID=$(docker exec gofr-vault vault kv get -format=json secret/gofr-iq/auth/groups/_index/names 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin)['data']['data']['admin'])")
echo "✓ Public Group UUID: $PUBLIC_GROUP_UUID"
echo "✓ Admin Group UUID: $ADMIN_GROUP_UUID"
echo ""

echo "=== Bootstrap Complete ==="
echo ""
echo "Environment Variables Set:"
echo "  PUBLIC_GROUP_UUID=$PUBLIC_GROUP_UUID"
echo "  ADMIN_GROUP_UUID=$ADMIN_GROUP_UUID"
echo "  GOFR_IQ_PUBLIC_TOKEN=${GOFR_IQ_PUBLIC_TOKEN:0:50}..."
echo "  GOFR_IQ_ADMIN_TOKEN=${GOFR_IQ_ADMIN_TOKEN:0:50}..."
echo ""
echo "Save these to a file:"
echo "  cat > .env.bootstrap << EOF"
echo "export PUBLIC_GROUP_UUID=\"$PUBLIC_GROUP_UUID\""
echo "export ADMIN_GROUP_UUID=\"$ADMIN_GROUP_UUID\""
echo "export GOFR_IQ_PUBLIC_TOKEN=\"$GOFR_IQ_PUBLIC_TOKEN\""
echo "export GOFR_IQ_ADMIN_TOKEN=\"$GOFR_IQ_ADMIN_TOKEN\""
echo "EOF"
echo ""
echo "Next steps:"
echo "  1. Create sources: See examples in Step 4 above"
echo "  2. Ingest documents: See examples in Step 5 above"
echo "  3. Query documents: See examples in Step 6 above"
echo ""
echo "For help: See docs/getting-started/bootstrap.md"
```

Save this as `scripts/bootstrap_complete.sh` and make it executable:

```bash
chmod +x scripts/bootstrap_complete.sh
```

---

## Environment Variables Reference

After bootstrap, these key variables should be set:

| Variable | Description | Example |
|----------|-------------|---------|
| `PUBLIC_GROUP_UUID` | UUID of the public group | `0a966f51-f9a2-4d5e-affc-ca4a6d184e84` |
| `ADMIN_GROUP_UUID` | UUID of the admin group | `a14c685b-1ee3-4cc2-ba73-de24f5c58b29` |
| `GOFR_IQ_PUBLIC_TOKEN` | JWT token for public group access | `eyJhbGciOiJIUzI1NiIs...` |
| `GOFR_IQ_ADMIN_TOKEN` | JWT token for admin group access | `eyJhbGciOiJIUzI1NiIs...` |
| `SOURCE_GUID` | UUID of your news source | `<generated-uuid>` |

**Save to file for reuse:**

```bash
cat > .env.bootstrap << EOF
export PUBLIC_GROUP_UUID="$PUBLIC_GROUP_UUID"
export ADMIN_GROUP_UUID="$ADMIN_GROUP_UUID"
export GOFR_IQ_PUBLIC_TOKEN="$GOFR_IQ_PUBLIC_TOKEN"
export GOFR_IQ_ADMIN_TOKEN="$GOFR_IQ_ADMIN_TOKEN"
export SOURCE_GUID="$SOURCE_GUID"
EOF

# Load in future sessions
source .env.bootstrap
```

---

## What You Now Have

After completing this bootstrap:

1. ✅ **Running Infrastructure**
   - Vault for authentication (port 8201)
   - Neo4j for graph data (ports 7474, 7687)
   - ChromaDB for vector search (port 8000)

2. ✅ **Running Services**
   - MCP server for core logic (port 8080)
   - MCPO API wrapper for OpenWebUI (port 8081)
   - Web health check endpoint (port 8082)

3. ✅ **Authentication Setup**
   - `public` group created with UUID
   - `admin` group created with UUID
   - Bootstrap tokens generated for both groups (10-year expiry)

4. ✅ **Data Model Ready**
   - Source created (Reuters example)
   - Document ingested (market update example)
   - Can query and retrieve documents

5. ✅ **Security Enabled**
   - Group-based access control active
   - All data scoped to group UUIDs
   - JWT tokens for authentication

---

## Common Operations

### Create Additional Sources

```bash
./scripts/manage_source.sh create \
  --name "Bloomberg" \
  --url "https://www.bloomberg.com" \
  --description "Financial news and data" \
  --source-type "financial_news" \
  --group-guid "${PUBLIC_GROUP_UUID}" \
  --host gofr-iq-mcp
```

### Ingest More Documents

```bash
/tmp/mcp_call.sh gofr-iq-mcp 8080 ingest_document "{
  \"title\": \"Your Title\",
  \"content\": \"Your content here...\",
  \"source_guid\": \"${SOURCE_GUID}\",
  \"group_guid\": \"${PUBLIC_GROUP_UUID}\",
  \"language\": \"en\"
}"
```

### Search Documents

```bash
/tmp/mcp_call.sh gofr-iq-mcp 8080 query_documents "{
  \"query\": \"your search terms\",
  \"group_guid\": \"${PUBLIC_GROUP_UUID}\",
  \"limit\": 10
}"
```

### List All Sources

```bash
./scripts/manage_source.sh list --host gofr-iq-mcp
```

**Note:** For document ingestion and queries, continue using the MCP helper script (`/tmp/mcp_call.sh`) or call the MCP API directly. Source management operations should use `manage_source.sh`.

---

## Troubleshooting

### Services Not Starting

```bash
# Check service logs
docker compose logs vault
docker compose logs neo4j
docker compose logs chromadb
docker compose logs mcp

# Restart specific service
docker compose restart mcp
```

### Groups Not Created

```bash
# Re-run bootstrap
./scripts/bootstrap_groups.sh

# Check Vault connection
docker exec gofr-vault vault status
```

### MCP Connection Refused

```bash
# Verify MCP is running
docker ps | grep gofr-iq-mcp

# Check MCP health
curl http://localhost:8080/health
```

### Port Conflicts

```bash
# Check if ports are available
netstat -tulpn | grep -E "8080|8081|8082|8201|7474|7687|8000"

# Update ports in lib/gofr-common/config/gofr_ports.sh if needed
```

---

## Next Steps

- **[Quick Start Guide](quick-start.md)** - Basic usage examples
- **[Security Model](../architecture/security.md)** - Understanding group-based access control
- **[API Reference](../reference/mcp-tools.md)** - Complete MCP tool documentation
- **[Development Guide](../development/setup.md)** - Setting up development environment

---

## Related Documentation

- [Group-Based Security Model](../architecture/security.md)
- [MCP Server Documentation](../reference/mcp-server.md)
- [Authentication & Authorization](../features/authentication.md)
- [Docker Deployment](../reference/docker.md)
