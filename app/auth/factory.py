"""Auth service factory (Vault-only; align to gofr-doc pattern).

This module builds a gofr-common AuthService for gofr-iq using:
- VaultIdentity (preferred) via /run/secrets/vault_creds, with auto-renewal
- JwtSecretProvider reading JWT signing secret from Vault
- Vault-backed token/group stores under the shared prefix (gofr/auth)

Environment Variables (Option A; GOFR_IQ_* everywhere):
    GOFR_IQ_AUTH_BACKEND=vault
    GOFR_IQ_VAULT_URL=http://gofr-vault:8201
    GOFR_IQ_VAULT_TOKEN=... (dev/test only; prod should use VaultIdentity)
    GOFR_IQ_VAULT_ROLE_ID / GOFR_IQ_VAULT_SECRET_ID (optional env AppRole fallback)
    GOFR_IQ_VAULT_PATH_PREFIX=gofr/auth
    GOFR_IQ_VAULT_MOUNT_POINT=secret
"""

from typing import Optional, Tuple

from gofr_common.auth import AuthService, GroupRegistry
from gofr_common.auth.backends import (
    FactoryError,
    GroupStore,
    TokenStore,
    create_stores_from_env,
    create_vault_client_from_env,
)
from gofr_common.auth.jwt_secret_provider import JwtSecretProvider
from gofr_common.auth.backends.vault_client import VaultClient

from app.logger import StructuredLogger

logger = StructuredLogger(name="auth-factory")


def create_stores(
    prefix: str = "GOFR_IQ",
) -> Tuple[TokenStore, GroupStore]:
    """Create token and group stores from environment.
    
    Args:
        prefix: Environment variable prefix (default: "GOFR")
        
    Returns:
        Tuple of (TokenStore, GroupStore)
    """
    return create_stores_from_env(prefix=prefix, logger=None)


def create_auth_service(
    *,
    prefix: str = "GOFR_IQ",
    audience: str = "gofr-api",
    vault_jwt_secret_path: str = "gofr/config/jwt-signing-secret",
    vault_client: Optional[VaultClient] = None,
    token_store: Optional[TokenStore] = None,
    group_store: Optional[GroupStore] = None,
) -> AuthService:
    """Create AuthService using Vault as source of truth.

    Returns an AuthService wired to:
    - Vault-backed token/group stores (shared prefix)
    - JwtSecretProvider for JWT signing secret
    - Fixed audience: gofr-api
    """
    try:
        client = vault_client or create_vault_client_from_env(prefix)

        if token_store is None or group_store is None:
            token_store, group_store = create_stores_from_env(prefix, vault_client=client)

        group_registry = GroupRegistry(store=group_store)

        secret_provider = JwtSecretProvider(
            vault_client=client,
            vault_path=vault_jwt_secret_path,
        )

        return AuthService(
            token_store=token_store,
            group_registry=group_registry,
            secret_provider=secret_provider,
            env_prefix=prefix,
            audience=audience,
        )
    except FactoryError as exc:
        logger.error(
            "Failed to create AuthService",
            cause_type=type(exc).__name__,
            error=str(exc),
            prefix=prefix,
            audience=audience,
            vault_jwt_secret_path=vault_jwt_secret_path,
            remediation="Verify GOFR_IQ_* Vault env vars or /run/secrets/vault_creds mount, then retry",
        )
        raise


__all__ = [
    "create_stores",
    "create_auth_service",
]
