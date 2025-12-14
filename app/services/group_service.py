"""Group Service for GoFr-IQ.

Provides group-based access control following the gofr-plot model:
- Extract group from JWT token
- Default to "public" for unauthenticated requests
- Validate group access for all operations
- One token = one group (strict 1:1 mapping)

Users needing access to multiple groups receive multiple tokens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gofr_common.auth import AuthService, TokenInfo

if TYPE_CHECKING:
    pass


# Public group constants
PUBLIC_GROUP = "public"
"""Default group for unauthenticated requests. Readable by all, writable by admins."""


class GroupAccessDeniedError(Exception):
    """Raised when access to a group is denied."""

    def __init__(
        self,
        group_guid: str,
        permitted_groups: list[str] | None = None,
        message: str | None = None,
    ) -> None:
        self.group_guid = group_guid
        self.permitted_groups = permitted_groups or []
        msg = message or f"Access denied to group '{group_guid}'"
        if permitted_groups:
            msg += f" (permitted: {permitted_groups})"
        super().__init__(msg)


class GroupService:
    """Service for group-based access control.
    
    Follows the gofr-plot model where:
    - Group is extracted from JWT token at request level
    - Unauthenticated requests get "public" group
    - Storage/graph operations filter by permitted groups
    
    Attributes:
        auth_service: Optional AuthService for token validation
    """

    def __init__(self, auth_service: AuthService | None = None) -> None:
        """Initialize the group service.
        
        Args:
            auth_service: AuthService instance for token validation.
                         If None, all requests are treated as public.
        """
        self.auth_service = auth_service

    def extract_group(self, token_info: TokenInfo | None) -> str:
        """Extract group from token info or return public.
        
        This follows the gofr-plot pattern:
            group = token_info.group if token_info else "public"
        
        Args:
            token_info: TokenInfo from JWT validation, or None if unauthenticated
            
        Returns:
            Group string - either the token's group or "public"
        """
        if token_info is not None:
            return token_info.group
        return PUBLIC_GROUP

    def get_permitted_groups(self, token_info: TokenInfo | None) -> list[str]:
        """Get all groups a user can access.
        
        All users can access public content. Authenticated users can also
        access their token's group.
        
        Args:
            token_info: TokenInfo from JWT validation, or None if unauthenticated
            
        Returns:
            List of group strings the user can read from.
            Always includes PUBLIC_GROUP.
        """
        groups = [PUBLIC_GROUP]
        if token_info is not None:
            user_group = token_info.group
            if user_group != PUBLIC_GROUP and user_group not in groups:
                groups.append(user_group)
        return groups

    def get_write_group(self, token_info: TokenInfo | None) -> str | None:
        """Get the group a user can write to.
        
        Only authenticated users can write, and only to their token's group.
        Public group is read-only for regular users.
        
        Args:
            token_info: TokenInfo from JWT validation, or None if unauthenticated
            
        Returns:
            Group string the user can write to, or None if no write access.
        """
        if token_info is None:
            return None
        return token_info.group

    def validate_read_access(
        self,
        token_info: TokenInfo | None,
        group: str,
    ) -> bool:
        """Validate that a user can read from a group.
        
        Args:
            token_info: TokenInfo from JWT validation
            group: Group to check access for
            
        Returns:
            True if access is allowed, False otherwise
        """
        permitted = self.get_permitted_groups(token_info)
        return group in permitted

    def validate_write_access(
        self,
        token_info: TokenInfo | None,
        group: str,
    ) -> bool:
        """Validate that a user can write to a group.
        
        Args:
            token_info: TokenInfo from JWT validation
            group: Group to check access for
            
        Returns:
            True if write access is allowed, False otherwise
        """
        write_group = self.get_write_group(token_info)
        if write_group is None:
            return False
        return group == write_group

    def is_public_group(self, group: str) -> bool:
        """Check if a group is the public group.
        
        Args:
            group: Group string to check
            
        Returns:
            True if this is the public group
        """
        return group == PUBLIC_GROUP


# Module-level singleton for convenience
_group_service: GroupService | None = None


def get_group_service() -> GroupService:
    """Get the global GroupService instance.
    
    Returns:
        GroupService singleton instance
        
    Raises:
        RuntimeError: If GroupService has not been initialized
    """
    global _group_service
    if _group_service is None:
        raise RuntimeError(
            "GroupService not initialized. Call init_group_service() first."
        )
    return _group_service


def init_group_service(auth_service: AuthService | None = None) -> GroupService:
    """Initialize the global GroupService instance.
    
    Args:
        auth_service: Optional AuthService for token validation
        
    Returns:
        The initialized GroupService instance
    """
    global _group_service
    _group_service = GroupService(auth_service=auth_service)
    return _group_service


def extract_group(token_info: TokenInfo | None) -> str:
    """Convenience function to extract group from token.
    
    Can be used without initializing the global service.
    
    Args:
        token_info: TokenInfo from JWT validation
        
    Returns:
        Group string - either the token's group or "public"
    """
    if token_info is not None:
        return token_info.group
    return PUBLIC_GROUP


def get_permitted_groups(token_info: TokenInfo | None) -> list[str]:
    """Convenience function to get permitted groups.
    
    Can be used without initializing the global service.
    
    Args:
        token_info: TokenInfo from JWT validation
        
    Returns:
        List of groups the user can read from
    """
    groups = [PUBLIC_GROUP]
    if token_info is not None:
        user_group = token_info.group
        if user_group != PUBLIC_GROUP and user_group not in groups:
            groups.append(user_group)
    return groups


def get_permitted_groups_from_context(auth_service: AuthService | None = None) -> list[str]:
    """Get permitted groups from the current request context.
    
    Extracts the Authorization header from the request context (set by
    AuthHeaderMiddleware), validates the JWT token, and returns the
    permitted groups.
    
    Args:
        auth_service: Optional AuthService for token validation.
                     If not provided, uses the global GroupService's auth_service.
        
    Returns:
        List of groups the user can read from. Returns [PUBLIC_GROUP]
        if no valid token is present.
    """
    from gofr_common.web import get_auth_header_from_context
    
    # Get auth header from context (set by AuthHeaderMiddleware)
    auth_header = get_auth_header_from_context()
    
    # No auth header = public access only
    if not auth_header:
        return [PUBLIC_GROUP]
    
    # Extract Bearer token
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]  # Remove "Bearer " prefix
    else:
        return [PUBLIC_GROUP]
    
    # Get auth service
    if auth_service is None:
        try:
            service = get_group_service()
            auth_service = service.auth_service
        except RuntimeError:
            # GroupService not initialized, can't validate token
            return [PUBLIC_GROUP]
    
    if auth_service is None:
        # No auth service configured, can't validate token
        return [PUBLIC_GROUP]
    
    try:
        token_info = auth_service.verify_token(token)
        return get_permitted_groups(token_info)
    except Exception:
        # Invalid token = public access only
        return [PUBLIC_GROUP]


def get_write_group_from_context(auth_service: AuthService | None = None) -> str | None:
    """Get the write group from the current request context.
    
    Extracts the Authorization header from the request context,
    validates the JWT token, and returns the group that can be
    written to (the token's primary group).
    
    Args:
        auth_service: Optional AuthService for token validation.
        
    Returns:
        The group the user can write to, or None if no valid token
        is present (anonymous users cannot write).
    """
    from gofr_common.web import get_auth_header_from_context
    
    auth_header = get_auth_header_from_context()
    
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header[7:]
    
    if auth_service is None:
        try:
            service = get_group_service()
            auth_service = service.auth_service
        except RuntimeError:
            return None
    
    if auth_service is None:
        return None
    
    try:
        token_info = auth_service.verify_token(token)
        return token_info.group
    except Exception:
        return None
