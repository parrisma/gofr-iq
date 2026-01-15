# Production Bootstrap Guide

Complete walkthrough for resetting and bootstrapping GOFR-IQ from scratch.

## Quick Start (Recommended)

**Single command** to start production with automatic Vault initialization:

```bash
# Fresh install (new Vault):
./docker/start-prod.sh --fresh

# With OpenRouter API key:
./docker/start-prod.sh --fresh --openrouter-key sk-or-v1-xxxxx

# Normal restart (existing Vault):
./docker/start-prod.sh

# Complete reset (wipe all data):
./docker/start-prod.sh --reset
```

That's it! The script handles:
1. ✅ Port configuration loading
2. ✅ Vault startup and health check
3. ✅ Automatic Vault initialization (if `--fresh`)
4. ✅ Automatic Vault unsealing
5. ✅ Bootstrap tokens creation
6. ✅ Environment file generation
7. ✅ All services startup

**Credentials are saved to:**
- `docker/.vault-init.env` - Vault root token and unseal key
- `docker/.env` - JWT secret and service credentials

---

## Manual Bootstrap (Advanced)

If you prefer manual control or the script fails:

### Prerequisites

- Docker and Docker Compose installed
- `uv` package manager installed
- Vault CLI installed (`vault` command)
- Access to project repository with gofr-common submodule

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
set -a && source ../lib/gofr-common/config/gofr_ports.env && set +a
docker compose up -d vault

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
export VAULT_TOKEN="$ROOT_TOKEN"
EOF

# Secure the file
chmod 600 docker/.vault-init.env

# Clean up temp file
rm /tmp/vault-init.json

echo "✅ Vault initialized. Credentials saved to docker/.vault-init.env"
```

### Step 4: Unseal Vault and Run Bootstrap

```bash
# Source credentials
source docker/.vault-init.env

# Unseal Vault
docker exec gofr-vault vault operator unseal "$VAULT_UNSEAL_KEY"

# Run bootstrap (from project root)
cd ..
uv run scripts/bootstrap.py
```

### Step 5: Start All Services

```bash
cd docker
source .env  # Load generated secrets
docker compose up -d
```

### Step 6: Verify

```bash
docker compose ps
# All services should show "healthy"
```

---

## Troubleshooting

### Vault Permission Denied

If services fail with "Permission denied" errors:

```bash
# Verify docker/.env has VAULT_ROOT_TOKEN
cat docker/.env | grep VAULT_ROOT_TOKEN

# Regenerate env from Vault:
source docker/.vault-init.env
./scripts/generate_envs.sh --mode prod
```

### Vault Sealed After Restart

Vault requires unsealing after every container restart:

```bash
source docker/.vault-init.env
docker exec gofr-vault vault operator unseal "$VAULT_UNSEAL_KEY"
```

Or use `start-prod.sh` which handles this automatically.

### MCP Container Restart Loop

Usually caused by missing credentials:

```bash
# Check logs
docker logs gofr-iq-mcp --tail 50

# Ensure docker/.env exists and has:
# - GOFR_JWT_SECRET
# - VAULT_ROOT_TOKEN

# Recreate services with updated env
cd docker
source ../lib/gofr-common/config/gofr_ports.env
source .env
docker compose up -d --force-recreate
```

---

## Architecture Notes

### Vault Data Persistence

Vault uses file-based storage in production mode:
- Data persists in `gofr-vault-data` Docker volume
- **Unsealing required** after every Vault container restart
- Use `start-prod.sh` for automatic unsealing

### Bootstrap Tokens

Bootstrap creates two long-lived tokens (365 days):
- **Admin Token**: Full access to all groups
- **Public Token**: Read-only public access

Token UUIDs are stored in Vault at:
- `secret/gofr/config/bootstrap-tokens/admin-token-id`
- `secret/gofr/config/bootstrap-tokens/public-token-id`

### Service Token Flow

1. Services read `VAULT_ROOT_TOKEN` from environment
2. Services connect to Vault using this token
3. JWT secret loaded from `GOFR_JWT_SECRET` environment variable
4. Auth service initialized with Vault backend stores
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
