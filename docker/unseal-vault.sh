#!/bin/bash
# =============================================================================
# Vault Unseal Script
# =============================================================================
# Unseals Vault using keys from vault-secrets.env
# Required after every Vault container restart
#
# Usage:
#   ./unseal-vault.sh
# =============================================================================
set -e

cd "$(dirname "$0")"

# Check if vault-secrets.env exists
if [[ ! -f "vault-secrets.env" ]]; then
    echo "ERROR: vault-secrets.env not found"
    echo ""
    echo "If this is a fresh install:"
    echo "  1. Start infrastructure: ./start-swarm.sh --infra"
    echo "  2. Initialize Vault:     docker exec gofr-vault vault operator init"
    echo "  3. Copy template:        cp vault-secrets.env.template vault-secrets.env"
    echo "  4. Edit with init output: vim vault-secrets.env"
    echo "  5. Run this script again"
    exit 1
fi

# Load unseal keys
source vault-secrets.env

# Check Vault status
echo "Checking Vault status..."
SEALED=$(docker exec gofr-vault vault status -format=json 2>/dev/null | grep -o '"sealed":[^,]*' | cut -d: -f2)

if [[ "$SEALED" == "false" ]]; then
    echo "✓ Vault is already unsealed"
    exit 0
fi

echo "Vault is sealed. Unsealing with 3 keys..."

# Unseal with first 3 keys
echo "  Applying unseal key 1/3..."
docker exec gofr-vault vault operator unseal "$VAULT_UNSEAL_KEY_1" > /dev/null

echo "  Applying unseal key 2/3..."
docker exec gofr-vault vault operator unseal "$VAULT_UNSEAL_KEY_2" > /dev/null

echo "  Applying unseal key 3/3..."
docker exec gofr-vault vault operator unseal "$VAULT_UNSEAL_KEY_3" > /dev/null

# Verify
echo ""
echo "Verifying..."
docker exec gofr-vault vault status

echo ""
echo "✓ Vault unsealed successfully"
