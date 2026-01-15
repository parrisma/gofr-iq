#!/usr/bin/env python3
"""
Bootstrap Script for GOFR-IQ
============================
Atomically initializes Vault secrets and creates bootstrap tokens.

Prerequisites:
- Vault must be running and unsealed
- VAULT_TOKEN must be set (root token)
- VAULT_ADDR must be set (e.g., http://localhost:8200)

Usage:
    source docker/.vault-init.env
    uv run scripts/bootstrap.py [--rotate-tokens] [--openrouter-key KEY]

This script:
1. Configures Vault KV v2 engine
2. Generates and stores JWT signing secret
3. Stores API keys (if provided)
4. Initializes Auth service and reserved groups
5. Creates long-lived admin/public tokens (365 days)
6. Stores token UUIDs in Vault for reference
"""

import argparse
import secrets
import sys
import os
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import hvac  # type: ignore[import-untyped]
    from app.auth.service import AuthService  # type: ignore[import-not-found]
    from app.auth.token_store import VaultTokenStore  # type: ignore[import-not-found]
    from app.auth.group_registry import GroupRegistry  # type: ignore[import-not-found]
    from app.auth.group_store import VaultGroupStore  # type: ignore[import-not-found]
except ImportError as e:
    print(f"Error importing dependencies: {e}")
    print("Ensure you're running with: uv run scripts/bootstrap.py")
    sys.exit(1)


def verify_vault_connection(client: hvac.Client) -> bool:
    """Verify Vault is accessible and authenticated."""
    try:
        if not client.is_authenticated():
            print("❌ Vault authentication failed. Check VAULT_TOKEN.")
            return False
        
        # Check health
        health = client.sys.read_health_status(method='GET')
        if not health.get('initialized'):
            print("❌ Vault is not initialized.")
            return False
        if health.get('sealed'):
            print("❌ Vault is sealed. Run: vault operator unseal")
            return False
            
        print("✅ Vault connection verified")
        return True
    except Exception as e:
        print(f"❌ Failed to connect to Vault: {e}")
        return False


def enable_kv_engine(client: hvac.Client) -> bool:
    """Enable KV v2 secret engine if not already enabled."""
    try:
        mounts = client.sys.list_mounted_secrets_engines()
        if 'secret/' in mounts:
            print("✅ KV v2 engine already enabled at secret/")
            return True
        
        # Enable KV v2
        client.sys.enable_secrets_engine(
            backend_type='kv',
            path='secret',
            options={'version': '2'}
        )
        print("✅ Enabled KV v2 engine at secret/")
        return True
    except Exception as e:
        print(f"❌ Failed to enable KV engine: {e}")
        return False


def generate_and_store_jwt_secret(client: hvac.Client) -> str:
    """Generate JWT signing secret and store in Vault."""
    try:
        # Check if secret already exists
        try:
            existing = client.secrets.kv.v2.read_secret_version(
                path='gofr/config/jwt-signing-secret',
                mount_point='secret'
            )
            jwt_secret = existing['data']['data']['value']
            print("✅ Using existing JWT signing secret")
            return jwt_secret
        except hvac.exceptions.InvalidPath:  # type: ignore[attr-defined]
            pass  # Secret doesn't exist, create new one
        
        # Generate new secret
        jwt_secret = secrets.token_urlsafe(32)
        
        # Store in Vault
        client.secrets.kv.v2.create_or_update_secret(
            path='gofr/config/jwt-signing-secret',
            secret={'value': jwt_secret},
            mount_point='secret'
        )
        print("✅ Generated and stored JWT signing secret")
        return jwt_secret
    except Exception as e:
        print(f"❌ Failed to handle JWT secret: {e}")
        sys.exit(1)


def store_api_key(client: hvac.Client, key_name: str, key_value: str):
    """Store API key in Vault."""
    try:
        client.secrets.kv.v2.create_or_update_secret(
            path=f'gofr/config/api-keys/{key_name}',
            secret={'value': key_value},
            mount_point='secret'
        )
        print(f"✅ Stored API key: {key_name}")
    except Exception as e:
        print(f"❌ Failed to store API key {key_name}: {e}")


def initialize_auth_service(vault_client: hvac.Client, jwt_secret: str) -> AuthService:
    """Initialize Auth service with Vault backend."""
    try:
        # Create Auth service with Vault stores
        auth = AuthService(
            token_store=VaultTokenStore(vault_client),
            group_registry=GroupRegistry(VaultGroupStore(vault_client)),
            secret_key=jwt_secret
        )
        
        # GroupRegistry auto-creates reserved groups (admin, public) on init
        print("✅ Initialized Auth service with reserved groups (admin, public)")
        return auth
    except Exception as e:
        print(f"❌ Failed to initialize Auth service: {e}")
        sys.exit(1)


def create_bootstrap_tokens(auth: AuthService, vault_client: hvac.Client, rotate: bool = False):
    """Create long-lived bootstrap tokens and store UUIDs in Vault."""
    try:
        # Token lifetime: 365 days
        token_lifetime = 86400 * 365
        
        # Create admin token
        print("\n📝 Creating admin bootstrap token...")
        admin_result = auth.create_token(
            groups=["admin"],
            expires_in_seconds=token_lifetime,
            description="Bootstrap admin token (365-day lifetime)"
        )
        admin_token = admin_result['token']
        admin_uuid = admin_result['jti']
        
        # Create public token
        print("📝 Creating public bootstrap token...")
        public_result = auth.create_token(
            groups=["public"],
            expires_in_seconds=token_lifetime,
            description="Bootstrap public token (365-day lifetime)"
        )
        public_token = public_result['token']
        public_uuid = public_result['jti']
        
        # Store token UUIDs (NOT the JWT strings!) in Vault
        vault_client.secrets.kv.v2.create_or_update_secret(
            path='gofr/config/bootstrap-tokens/admin-token-id',
            secret={'value': admin_uuid},
            mount_point='secret'
        )
        vault_client.secrets.kv.v2.create_or_update_secret(
            path='gofr/config/bootstrap-tokens/public-token-id',
            secret={'value': public_uuid},
            mount_point='secret'
        )
        
        print("✅ Stored token UUIDs in Vault")
        
        # Print tokens to console (only time they're shown!)
        print("\n" + "="*70)
        print("🎉 Bootstrap Complete!")
        print("="*70)
        print("\n⚠️  SAVE THESE TOKENS SECURELY (they won't be shown again):\n")
        print(f"Admin Token (365-day):  {admin_token}\n")
        print(f"Public Token (365-day): {public_token}\n")
        print("="*70)
        print("\n📋 Next Steps:")
        print("1. Create service token:")
        print("   vault token create -policy=gofr-service-read -period=768h")
        print("2. Generate environment files:")
        print("   ./scripts/generate_envs.sh")
        print("3. Start services:")
        print("   cd docker && docker compose up -d")
        print("\n⏰ Token Rotation Reminder:")
        print("   Set calendar reminder to rotate tokens 30 days before expiry")
        print("   Run: ./scripts/bootstrap.py --rotate-tokens")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"❌ Failed to create bootstrap tokens: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Bootstrap GOFR-IQ Vault and Auth')
    parser.add_argument('--rotate-tokens', action='store_true',
                       help='Rotate existing bootstrap tokens')
    parser.add_argument('--openrouter-key', type=str,
                       help='OpenRouter API key to store in Vault')
    args = parser.parse_args()
    
    # Check required environment variables
    vault_addr = os.getenv('VAULT_ADDR')
    vault_token = os.getenv('VAULT_TOKEN')
    
    if not vault_addr:
        print("❌ VAULT_ADDR not set. Example: http://localhost:8200")
        sys.exit(1)
    if not vault_token:
        print("❌ VAULT_TOKEN not set. Source .vault-init.env first.")
        sys.exit(1)
    
    print("\n" + "="*70)
    print("🚀 GOFR-IQ Bootstrap")
    print("="*70)
    print(f"Vault: {vault_addr}")
    print(f"Mode: {'Token Rotation' if args.rotate_tokens else 'Initial Setup'}")
    print("="*70 + "\n")
    
    # Initialize Vault client
    client = hvac.Client(url=vault_addr, token=vault_token)
    
    # Step 1: Verify connection
    if not verify_vault_connection(client):
        sys.exit(1)
    
    # Step 2: Enable KV engine
    if not enable_kv_engine(client):
        sys.exit(1)
    
    # Step 3: Generate/retrieve JWT secret
    jwt_secret = generate_and_store_jwt_secret(client)
    
    # Step 4: Store API keys if provided
    if args.openrouter_key:
        store_api_key(client, 'openrouter', args.openrouter_key)
    
    # Step 5: Initialize Auth service
    auth = initialize_auth_service(client, jwt_secret)
    
    # Step 6: Create bootstrap tokens
    create_bootstrap_tokens(auth, client, rotate=args.rotate_tokens)


if __name__ == '__main__':
    main()
