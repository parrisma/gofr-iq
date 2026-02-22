#!/usr/bin/env python3
"""
Bootstrap Script for GOFR-IQ
============================
Atomically initializes Vault secrets and creates bootstrap tokens.

Can auto-initialize and unseal Vault if running fresh.

Prerequisites:
- Vault must be running
- For existing Vault: VAULT_TOKEN must be set (root token)
- For fresh Vault: Script will initialize and save credentials

Usage:
    # Fresh install (auto-init):
    uv run scripts/bootstrap.py --auto-init

    # Existing Vault (credentials in secrets/):
    uv run scripts/bootstrap.py

    # Rotate tokens:
    uv run scripts/bootstrap.py --rotate-tokens

RECOVERY:
    If 'secrets/' directory is lost, you effectively lose access to the Vault.
    See scripts/readme.md for recovery steps (requires volume reset).

This script:
1. (Optional) Initializes Vault and saves credentials
2. (Optional) Unseals Vault
3. Configures Vault KV v2 engine
4. Generates and stores JWT signing secret
5. Stores API keys (if provided)
6. Initializes Auth service and reserved groups
7. Creates long-lived admin/public tokens (365 days)
8. Stores token UUIDs in Vault for reference
9. Generates docker/.env with secrets
"""

import argparse
import secrets
import sys
import os
import stat
import json
from pathlib import Path
from typing import Optional

# Add project root and gofr-common to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "gofr-common" / "src"))

try:
    import hvac  # type: ignore[import-untyped]
    from gofr_common.auth.service import AuthService  # type: ignore[import-not-found]
    from gofr_common.auth.backends.vault import VaultTokenStore, VaultGroupStore  # type: ignore[import-not-found]
    from gofr_common.auth.backends.vault_client import VaultClient  # type: ignore[import-not-found]
    from gofr_common.auth.backends.vault_config import VaultConfig  # type: ignore[import-not-found]
    from gofr_common.auth.groups import GroupRegistry  # type: ignore[import-not-found]
    from gofr_common.auth.jwt_secret_provider import JwtSecretProvider  # type: ignore[import-not-found]
except ImportError as e:
    print(f"Error importing dependencies: {e}")
    print("Ensure you're running with: uv run scripts/bootstrap.py")
    sys.exit(1)

# Import centralized Vault bootstrap from gofr-common
try:
    from gofr_common.vault import VaultBootstrap, VaultCredentials
except ImportError:
    # Fallback for when gofr-common is not installed
    VaultBootstrap = None
    VaultCredentials = None


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SECRETS_DIR = PROJECT_ROOT / "secrets"
VAULT_ROOT_TOKEN_FILE = SECRETS_DIR / "vault_root_token"
VAULT_UNSEAL_KEY_FILE = SECRETS_DIR / "vault_unseal_key"
DOCKER_ENV_FILE = PROJECT_ROOT / "docker" / ".env"
BOOTSTRAP_TOKEN_FILE = SECRETS_DIR / "bootstrap_tokens.json"


def ensure_secrets_dir():
    """Ensure secrets directory exists with strict permissions (0700)."""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.chmod(stat.S_IRWXU)  # 0700
    print(f"🔒 Secured {SECRETS_DIR} (permission 0700)")


# Use centralized VaultBootstrap if available
def get_vault_bootstrap(vault_addr: str):  # type: ignore[return]
    """Get VaultBootstrap instance (centralized from gofr-common)."""
    if VaultBootstrap is not None:
        return VaultBootstrap(vault_addr)
    raise ImportError("VaultBootstrap not available - install gofr-common")


def check_vault_status(vault_addr: str) -> dict:
    """Check Vault status without authentication."""
    import urllib.request
    import urllib.error
    import json
    try:
        req = urllib.request.Request(f"{vault_addr}/v1/sys/health", method='GET')
        # Vault returns different status codes for different states, all are valid responses
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 - controlled URL (Vault health endpoint)
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # Vault uses HTTP errors for status (e.g., 503 = sealed, 501 = not initialized)
            return json.loads(e.read())
    except Exception as e:
        return {"error": str(e)}


def initialize_vault(vault_addr: str) -> tuple[str, str]:
    """Initialize Vault and return (root_token, unseal_key)."""
    import urllib.request
    import json
    
    print("🔧 Initializing Vault (1 unseal key, threshold 1)...")
    
    data = json.dumps({"secret_shares": 1, "secret_threshold": 1}).encode()
    req = urllib.request.Request(
        f"{vault_addr}/v1/sys/init",
        data=data,
        headers={"Content-Type": "application/json"},
        method='PUT'
    )
    
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 - controlled URL (Vault init endpoint)
        result = json.loads(resp.read())
    
    root_token = result["root_token"]
    unseal_key = result["keys"][0]  # Single key for simplicity
    
    print("✅ Vault initialized successfully")
    return root_token, unseal_key


def unseal_vault(vault_addr: str, unseal_key: str) -> bool:
    """Unseal Vault with the given key."""
    import urllib.request
    import json
    
    print("🔓 Unsealing Vault...")
    
    data = json.dumps({"key": unseal_key}).encode()
    req = urllib.request.Request(
        f"{vault_addr}/v1/sys/unseal",
        data=data,
        headers={"Content-Type": "application/json"},
        method='PUT'
    )
    
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - controlled URL (Vault unseal endpoint)
        result = json.loads(resp.read())
    
    if not result.get("sealed", True):
        print("✅ Vault unsealed")
        return True
    else:
        print("❌ Vault still sealed")
        return False


def save_vault_credentials(root_token: str, unseal_key: str):
    """Save Vault credentials to secure storage."""
    ensure_secrets_dir()
    
    # Write Root Token
    VAULT_ROOT_TOKEN_FILE.write_text(root_token.strip())
    VAULT_ROOT_TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR) # 0600
    
    # Write Unseal Key
    VAULT_UNSEAL_KEY_FILE.write_text(unseal_key.strip())
    VAULT_UNSEAL_KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR) # 0600
    
    print(f"✅ Saved Vault credentials to {SECRETS_DIR}")
    print(f"   - Root Token: {VAULT_ROOT_TOKEN_FILE}")
    print(f"   - Unseal Key: {VAULT_UNSEAL_KEY_FILE}")


def generate_docker_env(
    jwt_secret: str,
    vault_token: str,
    neo4j_password: str,
    openrouter_key: Optional[str] = None,
) -> None:
    """Generate docker/.env with runtime configuration (NO SECRETS).
    
    ZERO-TRUST BOOTSTRAP PRINCIPLE:
    - ALL secrets stored ONLY in Vault
    - start-prod.sh loads secrets from Vault and exports as env vars
    - No secrets in .env file, no Docker secrets, no fallbacks
    """
    content = f"""# Generated by bootstrap.py - Runtime Configuration (NO SECRETS)
# {__import__('datetime').datetime.now().isoformat()}
#
# ZERO-TRUST BOOTSTRAP:
#   - ALL secrets stored ONLY in Vault
#   - start-prod.sh loads secrets from Vault before starting services
#   - Services authenticate to Vault via: /run/secrets/vault_creds (AppRole)
#   - If Vault unavailable or secrets missing, startup fails immediately

# Neo4j connection (password loaded from Vault by start-prod.sh)
GOFR_IQ_NEO4J_URI=bolt://gofr-neo4j:7687
GOFR_IQ_NEO4J_USER=neo4j

# Vault connection
GOFR_VAULT_URL=http://gofr-vault:8201
GOFR_VAULT_PATH_PREFIX=gofr/auth
GOFR_VAULT_MOUNT_POINT=secret

# Environment settings
GOFR_ENV=DEV
GOFR_LOG_LEVEL=INFO
GOFR_LOG_FORMAT=console
GOFR_AUTH_BACKEND=vault
"""
    
    DOCKER_ENV_FILE.write_text(content)
    print(f"✅ Generated {DOCKER_ENV_FILE} (no secrets)")
    print(f"   All secrets stored ONLY in Vault at: {SECRETS_DIR}/vault_root_token")


def verify_vault_connection(client: hvac.Client) -> bool:
    """Verify Vault is accessible and authenticated.
    
    After fresh initialization, Vault may need a moment to fully process
    authentication. Retry up to 10 times with small delays.
    """
    import time
    
    for attempt in range(10):
        try:
            # Try to make an authenticated request - read health is unauthenticated
            # so we need a different check
            try:
                # Try to read our own token info - this requires authentication
                token_info = client.auth.token.lookup_self()
                if not token_info:
                    if attempt < 9:
                        print(f"  Retry {attempt + 1}/10: Token lookup failed...")
                        time.sleep(0.5)
                        continue
                    print("❌ Vault authentication failed. Cannot lookup token.")
                    return False
            except Exception as e:
                if attempt < 9:
                    print(f"  Retry {attempt + 1}/10: {e}")
                    time.sleep(0.5)
                    continue
                print(f"❌ Vault authentication failed: {e}")
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
            if attempt < 9:
                print(f"  Retry {attempt + 1}/10: Connection error...")
                time.sleep(0.5)
                continue
            print(f"❌ Failed to connect to Vault: {e}")
            return False
    
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


def generate_and_store_neo4j_password(client: hvac.Client) -> str:
    """Generate Neo4j password and store in Vault."""
    try:
        # Check if password already exists
        try:
            existing = client.secrets.kv.v2.read_secret_version(
                path='gofr/config/neo4j-password',
                mount_point='secret'
            )
            neo4j_password = existing['data']['data']['value']
            print("✅ Using existing Neo4j password")
            return neo4j_password
        except hvac.exceptions.InvalidPath:  # type: ignore[attr-defined]
            pass  # Password doesn't exist, create new one
        
        # Generate new password (URL-safe, 32 bytes)
        neo4j_password = secrets.token_urlsafe(32)
        
        # Store in Vault
        client.secrets.kv.v2.create_or_update_secret(
            path='gofr/config/neo4j-password',
            secret={'value': neo4j_password},
            mount_point='secret'
        )
        print("✅ Generated and stored Neo4j password")
        return neo4j_password
    except Exception as e:
        print(f"❌ Failed to handle Neo4j password: {e}")
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


def initialize_auth_service(vault_url: str, vault_token: str, jwt_secret: str) -> tuple[AuthService, VaultClient]:
    """Initialize Auth service with Vault backend."""
    try:
        # Create VaultConfig and VaultClient
        vault_config = VaultConfig(
            url=vault_url,
            token=vault_token,
            mount_point="secret",
        )
        gofr_vault_client = VaultClient(vault_config)
        
        # Create JWT secret provider backed by Vault
        secret_provider = JwtSecretProvider(
            vault_client=gofr_vault_client,
            vault_path="gofr/config/jwt-signing-secret",
        )
        
        # Create Auth service with Vault stores
        auth = AuthService(
            token_store=VaultTokenStore(gofr_vault_client),
            group_registry=GroupRegistry(VaultGroupStore(gofr_vault_client)),
            secret_provider=secret_provider,
            audience="gofr-api",
        )
        
        # GroupRegistry auto-creates reserved groups (admin, public) on init
        print("✅ Initialized Auth service with reserved groups (admin, public)")
        return auth, gofr_vault_client
    except Exception as e:
        print(f"❌ Failed to initialize Auth service: {e}")
        sys.exit(1)


def create_bootstrap_tokens(auth: AuthService, hvac_client: hvac.Client, rotate: bool = False):
    """Create long-lived bootstrap tokens and store them in Vault and on disk (0600)."""
    try:
        # Token lifetime: 365 days
        token_lifetime = 86400 * 365
        
        # Create admin token
        print("\n📝 Creating admin bootstrap token...")
        admin_token = auth.create_token(
            groups=["admin"],
            expires_in_seconds=token_lifetime,
            name="bootstrap-admin",
        )
        # Extract jti from token by decoding (without verification since we just made it)
        import jwt as pyjwt
        admin_payload = pyjwt.decode(admin_token, options={"verify_signature": False})
        admin_uuid = admin_payload['jti']
        
        # Create public token
        print("📝 Creating public bootstrap token...")
        public_token = auth.create_token(
            groups=["public"],
            expires_in_seconds=token_lifetime,
            name="bootstrap-public",
        )
        public_payload = pyjwt.decode(public_token, options={"verify_signature": False})
        public_uuid = public_payload['jti']
        
        # Store token UUIDs (reference) in Vault using hvac client
        hvac_client.secrets.kv.v2.create_or_update_secret(
            path='gofr/config/bootstrap-tokens/admin-token-id',
            secret={'value': admin_uuid},
            mount_point='secret'
        )
        hvac_client.secrets.kv.v2.create_or_update_secret(
            path='gofr/config/bootstrap-tokens/public-token-id',
            secret={'value': public_uuid},
            mount_point='secret'
        )
        
        # Store full tokens in Vault (authoritative)
        hvac_client.secrets.kv.v2.create_or_update_secret(
            path='gofr/config/bootstrap-tokens/tokens',
            secret={'admin_token': admin_token, 'public_token': public_token},
            mount_point='secret'
        )
        print("✅ Stored bootstrap tokens in Vault (secret/gofr/config/bootstrap-tokens/tokens)")

        # Persist tokens to disk (0600) for automation consumers
        BOOTSTRAP_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        token_payload = {
            "admin_token": admin_token,
            "public_token": public_token,
            "ttl_seconds": token_lifetime,
        }
        BOOTSTRAP_TOKEN_FILE.write_text(json.dumps(token_payload, indent=2))
        BOOTSTRAP_TOKEN_FILE.chmod(0o600)
        print(f"✅ Saved bootstrap tokens to {BOOTSTRAP_TOKEN_FILE} (0600)")
        
        # Print tokens to console (only time they're shown!)
        print("\n" + "="*70)
        print("🎉 Bootstrap Complete!")
        print("="*70)
        print("\n⚠️  SAVE THESE TOKENS SECURELY (also stored in Vault and {BOOTSTRAP_TOKEN_FILE}):\n")
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
    parser.add_argument('--auto-init', action='store_true',
                       help='Auto-initialize and unseal Vault if needed')
    parser.add_argument('--rotate-tokens', action='store_true',
                       help='Rotate existing bootstrap tokens')
    parser.add_argument('--openrouter-key', type=str,
                       help='OpenRouter API key to store in Vault')
    args = parser.parse_args()
    
    # Default Vault address
    vault_addr = os.getenv('VAULT_ADDR', 'http://gofr-vault:8201')
    
    # For auto-init, ignore environment VAULT_TOKEN (we'll get a fresh one)
    # For existing Vault, try to load from env or secrets
    if args.auto_init:
        vault_token = None
        unseal_key = None
        print("🔄 Auto-init mode: Will generate fresh credentials")
    else:
        vault_token = os.getenv('VAULT_TOKEN')
        unseal_key = os.getenv('VAULT_UNSEAL_KEY')
        
        # Try to load from secrets dir if not in env
        if not vault_token and VAULT_ROOT_TOKEN_FILE.exists():
            print(f"🔑 Loading root token from {VAULT_ROOT_TOKEN_FILE}")
            vault_token = VAULT_ROOT_TOKEN_FILE.read_text().strip()
            
        if not unseal_key and VAULT_UNSEAL_KEY_FILE.exists():
            print(f"🔑 Loading unseal key from {VAULT_UNSEAL_KEY_FILE}")
            unseal_key = VAULT_UNSEAL_KEY_FILE.read_text().strip()

    print("\n" + "="*70)
    print("🚀 GOFR-IQ Bootstrap")
    print("="*70)
    print(f"Vault: {vault_addr}")
    print(f"Mode: {'Auto-Init' if args.auto_init else 'Token Rotation' if args.rotate_tokens else 'Standard'}")
    print("="*70 + "\n")
    
    # Centralized bootstrap: rely on VaultBootstrap for init/unseal/wait
    bootstrap = get_vault_bootstrap(vault_addr)

    if not bootstrap.wait_for_ready(max_attempts=60, delay=1):
        print(f"❌ Cannot reach Vault at {vault_addr}")
        print("   Ensure Vault container is running: docker compose up -d vault")
        sys.exit(1)

    creds = bootstrap.load_credentials(SECRETS_DIR)

    if args.auto_init:
        success, new_creds = bootstrap.auto_init_and_unseal(SECRETS_DIR)
        if not success:
            sys.exit(1)
        if new_creds:
            creds = new_creds
    else:
        status = bootstrap.get_status()
        if status["http_code"] == bootstrap.STATUS_NOT_INITIALIZED:
            print("❌ Vault is not initialized. Run with --auto-init for fresh install")
            sys.exit(1)
        if status["http_code"] == bootstrap.STATUS_SEALED:
            key_to_use = unseal_key or (creds.unseal_key if creds else None)
            if not key_to_use:
                print("❌ Vault is sealed. Provide VAULT_UNSEAL_KEY or ensure secrets/vault_unseal_key exists")
                sys.exit(1)
            if not bootstrap.ensure_unsealed(key_to_use):
                print("❌ Failed to unseal Vault")
                sys.exit(1)
        if not bootstrap.is_healthy():
            print("❌ Vault is not healthy after checks")
            sys.exit(1)

    # Refresh credentials after bootstrap actions
    if not vault_token and creds:
        vault_token = creds.root_token
    if not unseal_key and creds:
        unseal_key = creds.unseal_key

    if not vault_token:
        print("❌ VAULT_TOKEN not set (load from secrets/vault_root_token or use --auto-init)")
        sys.exit(1)
    
    # Debug: Show token prefix
    print(f"🔑 Using root token: {vault_token[:10]}...")
    
    # Initialize hvac client for low-level operations
    hvac_client = hvac.Client(url=vault_addr, token=vault_token)
    
    # Step 1: Verify connection
    if not verify_vault_connection(hvac_client):
        sys.exit(1)
    
    # Step 2: Enable KV engine
    if not enable_kv_engine(hvac_client):
        sys.exit(1)
    
    # Step 3: Generate/retrieve JWT secret
    jwt_secret = generate_and_store_jwt_secret(hvac_client)
    
    # Step 4: Generate/retrieve Neo4j password
    neo4j_password = generate_and_store_neo4j_password(hvac_client)
    
    # Step 5: Store API keys if provided
    openrouter_key = args.openrouter_key
    
    # If not provided as arg, try to get from existing Vault
    if not openrouter_key:
        try:
            existing = hvac_client.secrets.kv.v2.read_secret_version(
                path='gofr/config/api-keys/openrouter',
                mount_point='secret'
            )
            openrouter_key = existing['data']['data'].get('value')
            if openrouter_key:
                print("✅ Using existing OpenRouter key from Vault")
        except Exception:  # nosec B110 - non-critical: proceed without existing key
            pass
    
    # If still not found, prompt user (only if interactive)
    if not openrouter_key:
        if sys.stdin.isatty():
            print("\n" + "="*70)
            print("🔑 OpenRouter API Key Required")
            print("="*70)
            print("The OpenRouter API key is needed for LLM-powered features.")
            print("Get your key from: https://openrouter.ai/keys")
            print()
            print("Enter the key now, or press Enter to skip (you can add it later):")
            user_input = input("> ").strip()
            
            if user_input:
                openrouter_key = user_input
                print("✅ OpenRouter key will be stored in Vault")
            else:
                print("⚠️  Skipped - simulation and LLM features will require manual key setup")
        else:
            print("⚠️  Non-interactive mode: OpenRouter key not set")
            print("   Add later with: ./docker/start-prod.sh --openrouter-key YOUR_KEY")
    
    # Store in Vault if we have one
    if openrouter_key:
        store_api_key(hvac_client, 'openrouter', openrouter_key)
    
    # Step 6: Initialize Auth service (uses gofr-common VaultClient internally)
    auth, gofr_vault_client = initialize_auth_service(vault_addr, vault_token, jwt_secret)
    
    # Step 7: Create bootstrap tokens
    create_bootstrap_tokens(auth, hvac_client, rotate=args.rotate_tokens)
    
    # Step 8: Generate docker/.env
    generate_docker_env(jwt_secret, vault_token, neo4j_password, openrouter_key)
    
    print("\n✅ Bootstrap complete! Start services with:")
    print("   cd docker && source ../lib/gofr-common/config/gofr_ports.env && docker compose up -d")


if __name__ == '__main__':
    main()
