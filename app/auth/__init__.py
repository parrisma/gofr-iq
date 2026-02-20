"""Authentication module

Provides JWT-based authentication with multi-group access control.
Re-exports from gofr_common.auth v2 API.
"""

# Re-export everything from gofr_common.auth v2
from gofr_common.auth import (
    # Service
    AuthService,
    InvalidGroupError,
    TokenNotFoundError,
    TokenRevokedError,
    # Tokens
    TokenInfo,
    TokenRecord,
    # Groups
    Group,
    GroupRegistry,
    GroupRegistryError,
    ReservedGroupError,
    DuplicateGroupError,
    GroupNotFoundError,
    RESERVED_GROUPS,
    # Middleware
    get_auth_service,
    verify_token,
    verify_token_simple,
    optional_verify_token,
    init_auth_service,
    set_security_auditor,
    get_security_auditor,
    # Authorization helpers
    require_group,
    require_any_group,
    require_all_groups,
    require_admin,
    # Storage Protocols
    TokenStore,
    GroupStore,
    # Vault backends
    VaultConfig,
    VaultClient,
    VaultTokenStore,
    VaultGroupStore,
    VaultError,
    VaultConnectionError,
    VaultAuthenticationError,
    VaultNotFoundError,
    VaultPermissionError,
    # Factory functions
    create_token_store,
    create_group_store,
    create_stores_from_env,
    create_vault_client_from_env,
    # Storage exceptions
    StorageError,
    StorageUnavailableError,
    FactoryError,
)

from app.auth.group_access import (
    AccessDeniedError,
    AccessLevel,
    GroupAccessError,
    GroupAccessService,
    GroupClaims,
    TokenValidationError,
)

from app.auth.factory import (
    create_auth_service,
    create_stores,
)

__all__ = [
    # gofr_common.auth - Service
    "AuthService",
    "InvalidGroupError",
    "TokenNotFoundError",
    "TokenRevokedError",
    # gofr_common.auth - Tokens
    "TokenInfo",
    "TokenRecord",
    # gofr_common.auth - Groups
    "Group",
    "GroupRegistry",
    "GroupRegistryError",
    "ReservedGroupError",
    "DuplicateGroupError",
    "GroupNotFoundError",
    "RESERVED_GROUPS",
    # gofr_common.auth - Middleware
    "get_auth_service",
    "verify_token",
    "verify_token_simple",
    "optional_verify_token",
    "init_auth_service",
    "set_security_auditor",
    "get_security_auditor",
    # gofr_common.auth - Authorization helpers
    "require_group",
    "require_any_group",
    "require_all_groups",
    "require_admin",
    # gofr_common.auth - Storage Protocols
    "TokenStore",
    "GroupStore",
    # gofr_common.auth - Vault backends
    "VaultConfig",
    "VaultClient",
    "VaultTokenStore",
    "VaultGroupStore",
    "VaultError",
    "VaultConnectionError",
    "VaultAuthenticationError",
    "VaultNotFoundError",
    "VaultPermissionError",
    # gofr_common.auth - Factory functions
    "create_token_store",
    "create_group_store",
    "create_stores_from_env",
    "create_vault_client_from_env",
    # gofr_common.auth - Storage exceptions
    "StorageError",
    "StorageUnavailableError",
    "FactoryError",
    # group_access (gofr-iq specific)
    "AccessDeniedError",
    "AccessLevel",
    "GroupAccessError",
    "GroupAccessService",
    "GroupClaims",
    "TokenValidationError",
    # factory (gofr-iq specific)
    "create_auth_service",
    "create_stores",
]
