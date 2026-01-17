# GOFR-IQ Production Bootstrap Guide

Complete guide to bootstrap GOFR-IQ from scratch with production-mode Vault (persistent storage, manual unsealing).

## Prerequisites

```bash
cd /home/gofr/devroot/gofr-iq
```

---

## Overview: Production Vault Architecture

### Vault Modes Comparison

| Feature | Dev Mode (Old) | Production Mode (Current) |
|---------|----------------|---------------------------|
| Storage | In-memory | File-based persistent |
| Initialization | Auto | Manual (one-time) |
| Unsealing | Auto | Manual (every restart) |
| Root Token | Hardcoded | Generated unique |
| Data Persistence | ❌ Lost on restart | ✅ Persistent |
| Security | Low | High |

### Token Types & Storage

| Token Type | Purpose | Storage Location | Lifetime |
|------------|---------|------------------|----------|
| Vault Root Token | Infrastructure bootstrap & emergency | `vault-secrets.env` | Permanent |
| Vault Unseal Keys (5) | Unseal Vault after restart | `vault-secrets.env` | Permanent |
| Admin JWT Token | API admin operations | `vault-secrets.env` | 10 years |
| User JWT Tokens | API user access | Application | Configurable |

### Configuration File Hierarchy

```
lib/gofr-common/config/gofr_ports.env  # Ports (committed)
lib/gofr-common/.env                    # JWT secret (committed)
docker/vault-secrets.env                # Vault tokens (NOT committed)
```

### Reserved Groups

- `admin` - System administrators (manage sources, groups, tokens)
- `public` - Default group for public access

---

## Fresh Installation (First Time)

### Step 1: Start Infrastructure Only

```bash
cd /home/gofr/devroot/gofr-iq/docker
./start-swarm.sh --infra
```

**Services started:** `vault`, `neo4j`, `chromadb`

**Expected:** Vault will be **sealed** (unhealthy) - this is normal!

### Step 2: Initialize Vault (One Time Only)

```bash
docker exec gofr-vault vault operator init -key-shares=5 -key-threshold=3
```

⚠️ **CRITICAL**: Save these immediately! You cannot retrieve them later.

### Step 3: Create vault-secrets.env

```bash
cd /home/gofr/devroot/gofr-iq/docker
cp vault-secrets.env.template vault-secrets.env
```

Edit `vault-secrets.env` with your init values - example values below:

```bash
VAULT_ROOT_TOKEN=<your-root-token-here>
VAULT_UNSEAL_KEY_1=<unseal-key-1-here>
VAULT_UNSEAL_KEY_2=<unseal-key-2-here>
VAULT_UNSEAL_KEY_3=<unseal-key-3-here>
VAULT_UNSEAL_KEY_4=<unseal-key-4-here>
VAULT_UNSEAL_KEY_5=<unseal-key-5-here>
```

**Security:**
- File is already in `.gitignore` - never commit!
- Store keys in separate secure locations (not all in one file in production)
- Consider HSM or cloud KMS for production deployments

### Step 4: Unseal Vault

```bash
./unseal-vault.sh
```

**Or manually:**
```bash
source vault-secrets.env
docker exec gofr-vault vault operator unseal $VAULT_UNSEAL_KEY_1
docker exec gofr-vault vault operator unseal $VAULT_UNSEAL_KEY_2
docker exec gofr-vault vault operator unseal $VAULT_UNSEAL_KEY_3
```

**Verify:**
```bash
docker exec gofr-vault vault status
# Should show: Sealed: false
```

### Step 5: Enable KV Secrets Engine

```bash
source vault-secrets.env
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" gofr-vault \
  vault secrets enable -path=secret kv-v2
```

### Step 6: Bootstrap Authentication

```bash
source vault-secrets.env
source ../lib/gofr-common/.env  # For GOFR_JWT_SECRET

docker exec \
  -e GOFR_VAULT_TOKEN="$VAULT_ROOT_TOKEN" \
  -e GOFR_JWT_SECRET="$GOFR_JWT_SECRET" \
  gofr-iq-web \
  /home/gofr-iq/lib/gofr-common/scripts/bootstrap_auth.sh --docker
```

**Output will include:**
```
GOFR_PUBLIC_TOKEN=eyJhbGc...
GOFR_ADMIN_TOKEN=eyJhbGc...
```

**Add these to vault-secrets.env:**
```bash
echo "GOFR_ADMIN_TOKEN=eyJhbGc..." >> vault-secrets.env
echo "GOFR_PUBLIC_TOKEN=eyJhbGc..." >> vault-secrets.env
```

### Step 7: Start All Services

```bash
./start-swarm.sh
```

**Verify all healthy:**
```bash
docker compose ps
```

Expected: 6 services healthy
- `gofr-vault` (port 8201)
- `gofr-neo4j` (ports 7474, 7687)
- `gofr-chromadb` (port 8000)
- `gofr-iq-mcp` (port 8080)
- `gofr-iq-mcpo` (port 8081)
- `gofr-iq-web` (port 8082)

---

## Subsequent Restarts

After stopping/restarting containers:

```bash
cd /home/gofr/devroot/gofr-iq/docker

# 1. Start infrastructure
./start-swarm.sh --infra

# 2. Unseal Vault (required every restart)
./unseal-vault.sh

# 3. Start all services
./start-swarm.sh
```

**Why unseal every time?**
- Security feature - prevents unauthorized access to sealed data
- Requires 3 of 5 key holders to cooperate
- For auto-unseal, use cloud KMS (AWS/Azure/GCP)

---

## Verification & Testing

### Check Services

```bash
docker compose ps
docker logs gofr-iq-mcp --tail 20
```

### Verify Vault Data

```bash
source vault-secrets.env

# List groups
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" gofr-vault \
  vault kv get -format=json secret/gofr/auth/groups/_index/names \
  | python3 -m json.tool

# Expected output:
# {
#   "data": {
#     "data": {
#       "admin": "b75d2528-4497-46f7-834d-cd618883f2c1",
#       "public": "3734cb61-f194-4a7d-bf34-09fa9430607c"
#     }
#   }
# }
```

### Test API Access

```bash
source vault-secrets.env

# Health check (public endpoint)
curl http://localhost:8082/health

# List sources (admin token required)
curl -H "Authorization: Bearer $GOFR_ADMIN_TOKEN" \
  http://localhost:8080/sources
```

---
---

## Troubleshooting

### Vault Won't Unseal

**Symptoms:** `vault status` shows `Sealed: true` after applying 3 keys

**Solution:**
```bash
# Check if you're using the correct keys
source docker/vault-secrets.env
echo "Key 1: ${VAULT_UNSEAL_KEY_1:0:20}..."

# Verify vault status shows progress
docker exec gofr-vault vault status
# Should show: Unseal Progress 3/3 before final key
```

### Services Won't Start

**Symptoms:** MCP/MCPO services restart continuously

**Cause:** Vault is sealed or services can't access Vault token

**Solution:**
```bash
# 1. Check Vault status
docker exec gofr-vault vault status

# 2. If sealed, unseal it
cd /home/gofr/devroot/gofr-iq/docker
./unseal-vault.sh

# 3. Verify vault-secrets.env exists and is loaded
ls -l vault-secrets.env
source vault-secrets.env
echo "Token: ${VAULT_ROOT_TOKEN:0:20}..."

# 4. Restart services
./start-swarm.sh
```

### vault-secrets.env Not Found

**Symptoms:** Warning message: "vault-secrets.env not found"

**Solution:**
```bash
# If fresh install, follow Steps 1-6
# If you have the keys, recreate the file
cd /home/gofr/devroot/gofr-iq/docker
cp vault-secrets.env.template vault-secrets.env
# Edit and add your keys/tokens
```

### Permission Denied Errors

**Symptoms:** API returns 403 Forbidden when creating sources

**Cause:** Token doesn't have admin group membership

**Solution:**
```bash
# Verify your token has admin group
source docker/vault-secrets.env
echo $GOFR_ADMIN_TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | python3 -m json.tool

# Look for: "groups": ["admin"]
# If missing, re-run bootstrap auth (Step 6)
```

### Data Lost After Restart

**Cause:** You might be running in dev mode instead of production mode

**Verification:**
```bash
# Check if vault-config.hcl exists in the image
docker exec gofr-vault cat /vault/gofr-config.hcl

# Check storage type
docker exec gofr-vault vault status | grep "Storage Type"
# Should show: Storage Type    file
```

### Port Conflicts

**Symptoms:** Services fail to bind to ports

**Solution:**
```bash
# Check what's using the ports
netstat -tulpn | grep -E "8080|8081|8082|8201|7474|7687|8000"

# Update ports in config if needed
vim lib/gofr-common/config/gofr_ports.env
```

---

## Security Best Practices

### Vault Root Token

- **Use only for bootstrap** - Never for daily operations
- After bootstrap, store securely and don't access unless emergency
- Consider using a break-glass procedure for root token access

### Unseal Keys

- **Distribute to different people/systems** - Don't store all 5 together
- In production:
  - Use cloud KMS auto-unseal (AWS/Azure/GCP)
  - Or distribute keys to different key holders
  - Use HSM for key storage

### JWT Tokens

- **Admin tokens**: Rotate periodically, limit distribution
- **User tokens**: Set appropriate TTL (hours/days, not years)
- Store in secure environment variables or secrets manager
- Never commit to version control

### Production Deployment

```bash
# Use strong JWT secret (generate with)
openssl rand -base64 32

# Enable auto-unseal with cloud KMS
# See: https://developer.hashicorp.com/vault/docs/concepts/seal#auto-unseal

# Use TLS for all connections
# Configure reverse proxy (nginx/traefik) with Let's Encrypt
```

---

## Files Reference

### Configuration Files

| File | Purpose | Committed? |
|------|---------|------------|
| `lib/gofr-common/config/gofr_ports.env` | Port configuration | ✅ Yes |
| `lib/gofr-common/.env` | JWT secret, shared config | ✅ Yes |
| `docker/vault-secrets.env` | Vault tokens & keys | ❌ No (gitignored) |
| `docker/vault-secrets.env.template` | Template for secrets file | ✅ Yes |
| `docker/vault-config.hcl` | Vault production config | ✅ Yes (embedded in image) |

### Helper Scripts

| Script | Purpose |
|--------|---------|
| `docker/start-swarm.sh` | Start services (supports `--infra` flag) |
| `docker/unseal-vault.sh` | Unseal Vault with saved keys |
| `docker/stop-prod.sh` | Stop all services |
| `scripts/manage_source.sh` | Manage sources (admin only) |

---

## What You've Accomplished

After completing this bootstrap:

✅ **Production-grade Vault**
- Persistent file storage in `/vault/data`
- Manual unsealing with 5-key threshold
- KV v2 secrets engine enabled
- All auth data persists between restarts

✅ **Authentication System**
- `admin` group created with UUID
- `public` group created with UUID
- Long-lived JWT tokens generated (10 years)
- Root token secured in `vault-secrets.env`

✅ **Running Services**
- Infrastructure: Vault, Neo4j, ChromaDB
- Application: MCP, MCPO, Web
- All services healthy and connected

✅ **Security**
- Vault unsealed with distributed keys
- Group-based access control active
- Admin-only source management
- JWT authentication for all API calls

---

## Next Steps

1. **[Create Sources](../features/sources.md)** - Register your data sources
2. **[Ingest Documents](../features/ingestion.md)** - Add content to the knowledge graph
3. **[Query System](../features/querying.md)** - Search and retrieve information
4. **[User Management](../features/authentication.md)** - Create additional groups and tokens

---

## Related Documentation

- [Production Deployment Guide](../reference/docker.md)
- [Security Model](../architecture/security.md)
- [Vault Administration](../reference/vault.md)
- [MCP Server Documentation](../reference/mcp-server.md)
- [API Reference](../reference/api.md)

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

## Troubleshooting

### Problem: "Permission denied" when creating sources

**Cause**: Source management requires admin group membership.

**Solution**:
1. Verify your token has admin group:
   ```bash
   # Decode token to check groups claim
   echo $GOFR_IQ_ADMIN_TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | python3 -m json.tool
   ```
   
2. Look for `"groups": ["admin"]` in the output

3. If missing, recreate admin token:
   ```bash
   docker exec gofr-vault sh -c '
     export VAULT_ADDR=http://127.0.0.1:8200
     export VAULT_TOKEN=$(cat /vault/token/root.token)
     cd /app/gofr-common
     python -m gofr_common.auth.auth_manager tokens create --groups admin --ttl 87600h
   '
   ```

### Problem: "Authentication required" errors

**Cause**: Token not provided or expired.

**Solution**:
1. Verify token is set:
   ```bash
   echo "Token: ${GOFR_IQ_ADMIN_TOKEN:0:50}..."
   ```

2. Check token expiration:
   ```bash
   echo $GOFR_IQ_ADMIN_TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | python3 -c "import sys, json; print('Expires:', json.load(sys.stdin)['exp'])"
   ```

3. If expired, create new token with Step 2.1

### Problem: Vault is not running

**Cause**: Infrastructure not started.

**Solution**:
```bash
cd /home/gofr/devroot/gofr-iq/docker
./start-swarm.sh
docker compose ps  # Verify all services are healthy
```

### Problem: Groups don't exist in Vault

**Cause**: Bootstrap not completed.

**Solution**: Return to Step 2 and follow admin token creation process.

### Problem: Cannot find Vault root token

**Location**: The Vault root token is stored in the Vault container.

**Solution**:
```bash
# View root token
docker exec gofr-vault cat /vault/token/root.token

# Or use it directly
VAULT_ROOT_TOKEN=$(docker exec gofr-vault cat /vault/token/root.token)
echo "Root token: ${VAULT_ROOT_TOKEN:0:20}..."
```

**Security Note**: The root token is extremely powerful. Only use it for initial bootstrap. After creating the admin JWT token, rely on JWT tokens for all operations.

---

## Security Best Practices

1. **Root Token**: Only use during initial bootstrap. Never use for daily operations.

2. **Admin Token**: 
   - Store securely (environment variable, secrets manager)
   - Rotate periodically (create new, revoke old)
   - Limit distribution to authorized administrators

3. **User Tokens**:
   - Create with appropriate group membership
   - Set reasonable TTL (hours/days, not years)
   - Revoke when no longer needed

4. **Data Migration**:
   - Before deploying admin access control: Delete `data/storage/sources/` directory
   - Sources will be recreated by admins after deployment
   - This is necessary because source storage structure changed (group-based → flat)

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
