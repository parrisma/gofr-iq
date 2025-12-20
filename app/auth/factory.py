"""Auth service factory with pluggable backends.

This module provides factory functions to create AuthService instances
using the pluggable backend system from gofr-common.

Environment Variables:
    GOFR_AUTH_BACKEND: Backend type ("vault", "memory", "file")
    GOFR_VAULT_URL: Vault server URL
    GOFR_VAULT_TOKEN: Vault token (dev mode)
    GOFR_VAULT_ROLE_ID: AppRole role ID (production)
    GOFR_VAULT_SECRET_ID: AppRole secret ID (production)
    GOFR_VAULT_PATH_PREFIX: Path prefix in Vault (default: "gofr-iq")
    GOFR_VAULT_MOUNT_POINT: KV mount point (default: "secret")
"""

from typing import Optional, Tuple

from gofr_common.auth import (
    AuthService,
    GroupRegistry,
    create_stores_from_env,
)
from gofr_common.auth.backends import TokenStore, GroupStore

from app.logger import StructuredLogger

logger = StructuredLogger(name="auth-factory")


def create_stores(
    prefix: str = "GOFR",
) -> Tuple[TokenStore, GroupStore]:
    """Create token and group stores from environment.
    
    Args:
        prefix: Environment variable prefix (default: "GOFR")
        
    Returns:
        Tuple of (TokenStore, GroupStore)
    """
    return create_stores_from_env(prefix=prefix, logger=logger)


def create_auth_service(
    secret_key: str,
    *,
    prefix: str = "GOFR",
    env_prefix: str = "GOFR_IQ",
    token_store: Optional[TokenStore] = None,
    group_store: Optional[GroupStore] = None,
) -> AuthService:
    """Create AuthService using pluggable backend.
    
    Reads GOFR_AUTH_BACKEND environment variable (default: vault):
    - vault: HashiCorp Vault (recommended for all environments)
    - memory: In-memory (testing/fallback)
    - file: JSON files (legacy, not recommended)
    
    Args:
        secret_key: JWT signing secret
        prefix: Environment variable prefix for backend config (default: "GOFR")
        env_prefix: Environment variable prefix for JWT audience (default: "GOFR_IQ")
        token_store: Optional pre-created token store
        group_store: Optional pre-created group store
        
    Returns:
        Configured AuthService instance
    """
    if token_store is None or group_store is None:
        token_store, group_store = create_stores(prefix=prefix)
    
    groups = GroupRegistry(store=group_store)
    
    return AuthService(
        token_store=token_store,
        group_registry=groups,
        secret_key=secret_key,
        env_prefix=env_prefix,
    )


__all__ = [
    "create_stores",
    "create_auth_service",
]
