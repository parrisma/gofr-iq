"""Authentication module

Provides JWT-based authentication with group mapping.
Re-exports from gofr_common.auth for backward compatibility.
"""

# Re-export everything from gofr_common.auth
from gofr_common.auth import (
    AuthService,
    TokenInfo,
    get_auth_service,
    verify_token,
    optional_verify_token,
    init_auth_service,
)

from app.auth.group_access import (
    AccessDeniedError,
    AccessLevel,
    GroupAccessError,
    GroupAccessService,
    GroupClaims,
    GroupNotFoundError,
    TokenValidationError,
)

__all__ = [
    # gofr_common.auth
    "AuthService",
    "TokenInfo",
    "get_auth_service",
    "verify_token",
    "optional_verify_token",
    "init_auth_service",
    # group_access
    "AccessDeniedError",
    "AccessLevel",
    "GroupAccessError",
    "GroupAccessService",
    "GroupClaims",
    "GroupNotFoundError",
    "TokenValidationError",
]
