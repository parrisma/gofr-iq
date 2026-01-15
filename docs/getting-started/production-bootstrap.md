# Production Bootstrap Guide

Complete walkthrough for resetting and bootstrapping GOFR-IQ from scratch.

## Prerequisites

- Docker and Docker Compose installed
- `uv` package manager installed
- Vault CLI installed (`vault` command)
- Access to project repository with gofr-common submodule

## Complete Reset & Bootstrap

### Step 1: Reset Environment (Optional - Clean Slate)

If starting from a previously configured environment:

```bash
cd /home/gofr/devroot/gofr-iq

# Run reset script (will prompt for confirmation)
./docker/reset-prod.sh

# This removes:
# - All Docker volumes
# - data/storage, data/auth, data/vault, data/chroma, data/neo4j
# - .vault-init.env credentials
# - config/generated/* files
```

### Step 2: Start Vault

```bash
cd docker
docker compose up -d gofr-vault

# Wait for Vault to be ready
sleep 5
```

### Step 3: Initialize Vault

```bash
# Initialize Vault (creates unseal keys and root token)
docker exec gofr-vault vault operator init \
  -key-shares=1 \
  -key-threshold=1 \
  -format=json > /tmp/vault-init.json

# Extract credentials
UNSEAL_KEY=$(jq -r '.unseal_keys_b64[0]' /tmp/vault-init.json)
ROOT_TOKEN=$(jq -r '.root_token' /tmp/vault-init.json)

# Create credentials file
cat > docker/.vault-init.env <<EOF
export VAULT_UNSEAL_KEY="$UNSEAL_KEY"
export VAULT_ROOT_TOKEN="$ROOT_TOKEN"
export VAULT_TOKEN=\$VAULT_ROOT_TOKEN
export VAULT_ADDR="http://localhost:8200"
EOF

# Secure the file
chmod 600 docker/.vault-init.env

# Clean up temp file
rm /tmp/vault-init.json

echo "✅ Vault initialized. Credentials saved to docker/.vault-init.env"
```

### Step 4: Unseal Vault

```bash
# Source credentials
source docker/.vault-init.env

# Unseal Vault
docker exec -e VAULT_ADDR=http://localhost:8200 \
  gofr-vault vault operator unseal "$VAULT_UNSEAL_KEY"

# Verify status
docker exec -e VAULT_ADDR=http://localhost:8200 \
  -e VAULT_TOKEN="$VAULT_TOKEN" \
  gofr-vault vault status
```

### Step 5: Create Vault Service Policy & Token

```bash
# Create read-only policy for services
docker exec -e VAULT_ADDR=http://localhost:8200 \
  -e VAULT_TOKEN="$VAULT_TOKEN" \
  gofr-vault vault policy write gofr-service-read - <<'EOF'
# Read access to config secrets
path "secret/data/gofr/config/*" {
  capabilities = ["read", "list"]
}

# Read access to auth namespace
path "secret/data/gofr/auth/*" {
  capabilities = ["read", "list"]
}
EOF

# Create service token (renewable, 32-day period)
VAULT_SERVICE_TOKEN=$(docker exec \
  -e VAULT_ADDR=http://localhost:8200 \
  -e VAULT_TOKEN="$VAULT_TOKEN" \
  gofr-vault vault token create \
    -policy=gofr-service-read \
    -no-default-policy \
    -period=768h \
    -display-name="gofr-services" \
    -format=json | jq -r '.auth.client_token')

# Add to credentials file
echo "export VAULT_SERVICE_TOKEN='$VAULT_SERVICE_TOKEN'" >> docker/.vault-init.env

echo "✅ Service token created: ${VAULT_SERVICE_TOKEN:0:10}..."
```

### Step 6: Run Bootstrap Script

```bash
# Source credentials
source docker/.vault-init.env

# Run bootstrap (creates secrets, groups, tokens)
uv run scripts/bootstrap.py

# Optional: Provide OpenRouter API key
# uv run scripts/bootstrap.py --openrouter-key "sk-or-..."

# Save the admin and public tokens displayed in output!
```

**Bootstrap script performs:**
- ✅ Enables KV v2 secret engine
- ✅ Generates JWT signing secret
- ✅ Stores API keys (if provided)
- ✅ Initializes Auth service with admin/public groups
- ✅ Creates 365-day bootstrap tokens
- ✅ Stores token UUIDs in Vault

### Step 7: Generate Environment Files

```bash
# Generate secrets.env and docker/.env
VAULT_TOKEN=$VAULT_SERVICE_TOKEN ./scripts/generate_envs.sh

# Verify generation
ls -la config/generated/
ls -la docker/.env
```

### Step 8: Start All Services

```bash
cd docker
docker compose up -d

# Verify all services running
docker compose ps

# Check logs
docker compose logs -f gofr-iq-mcp
```

### Step 9: Verify Setup

```bash
# Source the generated secrets
source config/generated/secrets.env

# Test MCP server health
curl http://localhost:8080/health

# Test with admin token (from bootstrap output)
export ADMIN_TOKEN="<token-from-bootstrap>"
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8080/mcp/list_sources
```

## Troubleshooting

### Vault Not Unsealed

```bash
source docker/.vault-init.env
docker exec -e VAULT_ADDR=http://localhost:8200 \
  gofr-vault vault operator unseal "$VAULT_UNSEAL_KEY"
```

### Bootstrap Fails - "Not Authenticated"

```bash
# Verify VAULT_TOKEN is set
echo $VAULT_TOKEN

# Re-source credentials
source docker/.vault-init.env
```

### Services Can't Connect to Vault

```bash
# Check Vault is running
docker ps | grep vault

# Check service token is valid
docker exec -e VAULT_ADDR=http://localhost:8200 \
  -e VAULT_TOKEN="$VAULT_SERVICE_TOKEN" \
  gofr-vault vault token lookup
```

## Token Rotation

Set calendar reminder for ~335 days (30 days before expiry):

```bash
source docker/.vault-init.env
uv run scripts/bootstrap.py --rotate-tokens

# Save new tokens from output
# Update any external systems using old tokens
```

## Quick Reference

**Credentials File:** `docker/.vault-init.env` (gitignored)
**Generated Configs:** `config/generated/` (gitignored)
**Bootstrap Tokens:** Displayed once by bootstrap.py - save securely!
**Service Token:** In .vault-init.env, used by generate_envs.sh
