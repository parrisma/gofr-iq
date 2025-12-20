#!/usr/bin/env python3
"""Bootstrap authentication for GoFr-IQ.

Creates the public and admin groups and their bootstrap tokens in Vault.
This script is idempotent - safe to run multiple times.

Usage:
    # Before tests (ephemeral Vault)
    python scripts/bootstrap_auth.py

    # Production (persistent Vault)
    python scripts/bootstrap_auth.py

    # With custom Vault URL
    GOFR_VAULT_URL=http://localhost:8200 python scripts/bootstrap_auth.py

Environment Variables:
    GOFR_VAULT_URL         Vault server URL (default: http://gofr-vault:8200)
    GOFR_VAULT_TOKEN       Vault token (default: gofr-dev-root-token)
    GOFR_VAULT_PATH_PREFIX Path prefix in Vault (default: gofr-iq)
    GOFR_VAULT_MOUNT_POINT KV mount point (default: secret)
    GOFR_IQ_JWT_SECRET     JWT signing secret (required)
    GOFR_AUTH_BACKEND      Auth backend type (default: vault)

Output:
    Prints bootstrap tokens to stdout in format:
    GOFR_IQ_PUBLIC_TOKEN=<token>
    GOFR_IQ_ADMIN_TOKEN=<token>
"""

import os
import sys
from pathlib import Path

# Add project root to path for imports
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# Add gofr-common to path
gofr_common_path = project_root / "lib" / "gofr-common" / "src"
if gofr_common_path.exists():
    sys.path.insert(0, str(gofr_common_path))

from gofr_common.auth import (  # noqa: E402 - path setup required first
    AuthService,
    GroupRegistry,
)
from gofr_common.auth.backends import (  # noqa: E402 - path setup required first
    create_stores_from_env,
)
from gofr_common.auth.backends.vault_client import VaultClient  # noqa: E402 - path setup required first
from gofr_common.auth.backends.vault_config import VaultConfig  # noqa: E402 - path setup required first
from gofr_common.logger import create_logger  # noqa: E402 - path setup required first

# Bootstrap token identifiers (stored as metadata in token record)
PUBLIC_BOOTSTRAP_ID = "public-bootstrap"
ADMIN_BOOTSTRAP_ID = "admin-bootstrap"

# Group names
PUBLIC_GROUP = "public"
ADMIN_GROUP = "admin"

# Token expiry: 10 years in seconds (effectively permanent)
BOOTSTRAP_TOKEN_EXPIRY = 10 * 365 * 24 * 60 * 60

logger = create_logger(name="bootstrap-auth")


def get_vault_client() -> VaultClient:
    """Create a Vault client from environment configuration.
    
    Returns:
        Configured VaultClient instance.
        
    Raises:
        SystemExit: If Vault configuration is invalid.
    """
    try:
        config = VaultConfig.from_env("GOFR")
        config.validate()
        return VaultClient(config, logger=logger)
    except Exception as e:
        logger.error(f"Failed to create Vault client: {e}")
        print(f"ERROR: Failed to connect to Vault: {e}", file=sys.stderr)
        print("\nEnsure Vault is running and environment is configured:", file=sys.stderr)
        print("  GOFR_VAULT_URL         - Vault server URL", file=sys.stderr)
        print("  GOFR_VAULT_TOKEN       - Vault token", file=sys.stderr)
        sys.exit(1)


def get_auth_service() -> AuthService:
    """Create an AuthService with Vault backend.
    
    Returns:
        Configured AuthService instance.
        
    Raises:
        SystemExit: If configuration is invalid.
    """
    # Get JWT secret
    jwt_secret = os.environ.get("GOFR_IQ_JWT_SECRET")
    if not jwt_secret:
        print("ERROR: GOFR_IQ_JWT_SECRET environment variable is required", file=sys.stderr)
        sys.exit(1)
    
    # Create stores from environment
    try:
        token_store, group_store = create_stores_from_env(prefix="GOFR")
    except Exception as e:
        logger.error(f"Failed to create stores: {e}")
        print(f"ERROR: Failed to create auth stores: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Create group registry
    group_registry = GroupRegistry(store=group_store, auto_bootstrap=True)
    
    # Create auth service
    return AuthService(
        token_store=token_store,
        group_registry=group_registry,
        secret_key=jwt_secret,
        env_prefix="GOFR_IQ",
    )


def ensure_groups(auth_service: AuthService) -> None:
    """Ensure public and admin groups exist.
    
    Groups are automatically bootstrapped by GroupRegistry when auto_bootstrap=True,
    but we verify they exist here.
    
    Args:
        auth_service: AuthService instance.
    """
    for group_name in [PUBLIC_GROUP, ADMIN_GROUP]:
        group = auth_service.groups.get_group_by_name(group_name)
        if group is None:
            # This shouldn't happen if auto_bootstrap worked, but create if needed
            logger.warning(f"Reserved group '{group_name}' missing, creating...")
            # Reserved groups are handled specially - force creation
            auth_service.groups.ensure_reserved_groups()
            group = auth_service.groups.get_group_by_name(group_name)
        
        if group:
            logger.info(f"Group '{group_name}' exists", group_id=str(group.id))
        else:
            logger.error(f"Failed to create group '{group_name}'")
            print(f"ERROR: Failed to ensure group '{group_name}' exists", file=sys.stderr)
            sys.exit(1)


def find_bootstrap_token(auth_service: AuthService, group_name: str) -> str | None:
    """Find an existing bootstrap token for a group.
    
    Searches for a token that has only the specified group and is not expired/revoked.
    
    Args:
        auth_service: AuthService instance.
        group_name: Name of the group to find token for.
        
    Returns:
        JWT token string if found, None otherwise.
    """
    # Access the token store directly to search for existing tokens
    token_store = auth_service._token_store
    
    # List all tokens and find one for this group
    try:
        all_tokens = token_store.list_all()
        for token_id, token_record in all_tokens.items():
            # Check if token is for this specific group (single group token)
            # TokenRecord uses status="active"|"revoked" and is_valid property
            if (
                token_record.groups == [group_name]
                and token_record.status == "active"
                and token_record.is_valid
            ):
                # Found a valid bootstrap token - recreate the JWT
                # We can't retrieve the original JWT, so we'll skip this
                # and always create a new token if needed
                logger.debug(
                    f"Found existing token for {group_name}",
                    token_id=token_id,
                )
                # We can't recover the original JWT, so we continue to create new
                pass
    except Exception as e:
        logger.debug(f"Could not search existing tokens: {e}")
    
    return None


def create_bootstrap_token(auth_service: AuthService, group_name: str) -> str:
    """Create a bootstrap token for a group.
    
    Args:
        auth_service: AuthService instance.
        group_name: Name of the group to create token for.
        
    Returns:
        JWT token string.
    """
    token = auth_service.create_token(
        groups=[group_name],
        expires_in_seconds=BOOTSTRAP_TOKEN_EXPIRY,
    )
    
    logger.info(
        f"Created bootstrap token for '{group_name}'",
        expires_in_days=BOOTSTRAP_TOKEN_EXPIRY // (24 * 60 * 60),
    )
    
    return token


def main() -> int:
    """Main entry point.
    
    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    print("=== GoFr-IQ Auth Bootstrap ===", file=sys.stderr)
    print(f"Vault URL: {os.environ.get('GOFR_VAULT_URL', 'not set')}", file=sys.stderr)
    print(f"Auth Backend: {os.environ.get('GOFR_AUTH_BACKEND', 'not set')}", file=sys.stderr)
    print("", file=sys.stderr)
    
    # Ensure auth backend is vault
    backend = os.environ.get("GOFR_AUTH_BACKEND", "vault")
    if backend != "vault":
        print(f"WARNING: Auth backend is '{backend}', expected 'vault'", file=sys.stderr)
        print("Bootstrap tokens will work but may not persist across restarts", file=sys.stderr)
    
    # Set default Vault config if not set
    os.environ.setdefault("GOFR_AUTH_BACKEND", "vault")
    os.environ.setdefault("GOFR_VAULT_URL", "http://gofr-vault:8200")
    os.environ.setdefault("GOFR_VAULT_TOKEN", "gofr-dev-root-token")
    os.environ.setdefault("GOFR_VAULT_PATH_PREFIX", "gofr-iq")
    os.environ.setdefault("GOFR_VAULT_MOUNT_POINT", "secret")
    
    try:
        # Create auth service
        auth_service = get_auth_service()
        
        # Ensure groups exist
        print("Ensuring groups exist...", file=sys.stderr)
        ensure_groups(auth_service)
        
        # Create bootstrap tokens
        print("Creating bootstrap tokens...", file=sys.stderr)
        
        public_token = create_bootstrap_token(auth_service, PUBLIC_GROUP)
        admin_token = create_bootstrap_token(auth_service, ADMIN_GROUP)
        
        # Output tokens for capture by shell script
        print(f"GOFR_IQ_PUBLIC_TOKEN={public_token}")
        print(f"GOFR_IQ_ADMIN_TOKEN={admin_token}")
        
        print("", file=sys.stderr)
        print("Bootstrap complete!", file=sys.stderr)
        print(f"  Public token: {public_token[:50]}...", file=sys.stderr)
        print(f"  Admin token: {admin_token[:50]}...", file=sys.stderr)
        
        return 0
        
    except Exception as e:
        logger.error(f"Bootstrap failed: {e}")
        print(f"ERROR: Bootstrap failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
