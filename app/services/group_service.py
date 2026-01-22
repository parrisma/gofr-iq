"""Group Service for GoFr-IQ.

Provides group-based access control using gofr_common.auth v2:
- Extract groups from JWT token (multi-group support)
- Default to "public" for unauthenticated requests
- Validate group access for all operations
- Tokens can have multiple groups

The 'public' group is always accessible to all users.
"""

from __future__ import annotations

from gofr_common.auth import AuthService, TokenInfo


# Public group constant - matches gofr_common.auth reserved group
PUBLIC_GROUP = "public"
"""Default group for unauthenticated requests. Readable by all."""


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
    
    Uses gofr_common.auth v2 multi-group tokens:
    - Tokens can have multiple groups
    - Primary group = first group in token
    - Public group always included in permitted groups
    
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
        """Extract primary group from token info or return public.
        
        For multi-group tokens, returns the first (primary) group.
        
        Args:
            token_info: TokenInfo from JWT validation, or None if unauthenticated
            
        Returns:
            Primary group string - either the token's first group or "public"
        """
        if token_info is not None and token_info.groups:
            return token_info.groups[0]
        return PUBLIC_GROUP

    def get_permitted_groups(self, token_info: TokenInfo | None) -> list[str]:
        """Get all groups a user can access.
        
        Returns all groups from the token plus public.
        
        Args:
            token_info: TokenInfo from JWT validation, or None if unauthenticated
            
        Returns:
            List of group strings the user can read from.
            Always includes PUBLIC_GROUP.
        """
        groups = {PUBLIC_GROUP}
        if token_info is not None:
            groups.update(token_info.groups)
        return list(groups)

    def get_write_group(self, token_info: TokenInfo | None) -> str | None:
        """Get the primary group a user can write to.
        
        Only authenticated users can write, and writes go to their
        primary (first) group.
        
        Args:
            token_info: TokenInfo from JWT validation, or None if unauthenticated
            
        Returns:
            Primary group string the user can write to, or None if no write access.
        """
        if token_info is None or not token_info.groups:
            return None
        return token_info.groups[0]

    def get_write_groups(self, token_info: TokenInfo | None) -> list[str]:
        """Get all groups a user can write to.
        
        Returns all groups from the token (user can write to any of their groups).
        
        Args:
            token_info: TokenInfo from JWT validation, or None if unauthenticated
            
        Returns:
            List of groups the user can write to, empty if unauthenticated.
        """
        if token_info is None:
            return []
        return list(token_info.groups)

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
        
        User can write to any of their groups.
        
        Args:
            token_info: TokenInfo from JWT validation
            group: Group to check access for
            
        Returns:
            True if write access is allowed, False otherwise
        """
        if token_info is None:
            return False
        return token_info.has_group(group)

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
    """Convenience function to extract primary group from token.
    
    Can be used without initializing the global service.
    
    Args:
        token_info: TokenInfo from JWT validation
        
    Returns:
        Primary group string - either the token's first group or "public"
    """
    if token_info is not None and token_info.groups:
        return token_info.groups[0]
    return PUBLIC_GROUP


def get_permitted_groups(token_info: TokenInfo | None) -> list[str]:
    """Convenience function to get permitted groups.
    
    Can be used without initializing the global service.
    
    Args:
        token_info: TokenInfo from JWT validation
        
    Returns:
        List of groups the user can read from (all token groups + public)
    """
    groups = {PUBLIC_GROUP}
    if token_info is not None:
        groups.update(token_info.groups)
    return list(groups)


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
        # Vault backend requires store lookup (require_store=True)
        # Tokens are stored in Vault and must be verified against the store
        token_info = auth_service.verify_token(token, require_store=True)
        groups = get_permitted_groups(token_info)
        return groups
    except Exception:
        # Invalid token = public access only
        return [PUBLIC_GROUP]


def get_write_group_from_context(auth_service: AuthService | None = None) -> str | None:
    """Get the write group name from the current request context.
    
    Extracts the Authorization header from the request context,
    validates the JWT token, and returns the primary group name that can be
    written to (the token's first group).
    
    Args:
        auth_service: Optional AuthService for token validation.
        
    Returns:
        The primary group name the user can write to, or None if no valid token
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
        # Vault backend requires store lookup (require_store=True)
        token_info = auth_service.verify_token(token, require_store=True)
        if token_info.groups:
            return token_info.groups[0]  # Return primary group name
        return None
    except Exception:
        return None


def resolve_permitted_groups(
    auth_tokens: list[str] | None = None,
    auth_service: AuthService | None = None,
) -> list[str]:
    """Get permitted groups from explicit tokens OR context header.
    
    This function provides a unified way to extract permitted groups,
    supporting both:
    1. Explicit auth_tokens parameter (for MCPO proxy path where headers
       are not forwarded)
    2. Authorization header from request context (for direct MCP calls)
    
    Priority:
    1. If auth_tokens provided -> extract groups from all tokens
    2. Otherwise -> fall back to get_permitted_groups_from_context()
    3. Default: ["public"]
    
    Args:
        auth_tokens: Optional list of JWT tokens to extract groups from.
                    If provided, extracts and unions groups from all tokens.
        auth_service: Optional AuthService for token validation.
                     Falls back to global GroupService's auth_service.
    
    Returns:
        List of group IDs the caller can access. Always includes "public".
    """
    # If explicit tokens provided, extract groups from them
    if auth_tokens:
        return _extract_groups_from_tokens(auth_tokens, auth_service)
    
    # Otherwise, fall back to context-based extraction
    return get_permitted_groups_from_context(auth_service)


def _extract_groups_from_tokens(
    auth_tokens: list[str],
    auth_service: AuthService | None = None,
) -> list[str]:
    """Extract and union groups from a list of JWT tokens.
    
    Args:
        auth_tokens: List of JWT tokens (without "Bearer " prefix)
        auth_service: Optional AuthService for token validation.
        
    Returns:
        List of unique groups from all valid tokens, plus "public".
    """
    # Get auth service if not provided
    if auth_service is None:
        try:
            service = get_group_service()
            auth_service = service.auth_service
        except RuntimeError:
            return [PUBLIC_GROUP]
    
    if auth_service is None:
        return [PUBLIC_GROUP]
    
    # Extract groups from all tokens
    all_groups = {PUBLIC_GROUP}
    
    for token in auth_tokens:
        # Strip "Bearer " prefix if present (be lenient)
        if token.startswith("Bearer "):
            token = token[7:]
        
        try:
            # Vault backend requires store lookup (require_store=True)
            token_info = auth_service.verify_token(token, require_store=True)
            if token_info and token_info.groups:
                all_groups.update(token_info.groups)
        except Exception:  # nosec B110 - Intentionally continue on invalid tokens
            # Continue processing other tokens
            pass
    
    return list(all_groups)


def resolve_write_group(
    auth_tokens: list[str] | None = None,
    auth_service: AuthService | None = None,
) -> str | None:
    """Get the write group name from explicit tokens OR context header.
    
    This function provides a unified way to extract the primary write group,
    supporting both:
    1. Explicit auth_tokens parameter (for MCPO proxy path where headers
       are not forwarded)
    2. Authorization header from request context (for direct MCP calls)
    
    Priority:
    1. If auth_tokens provided -> extract primary group from first valid token
    2. Otherwise -> fall back to get_write_group_from_context()
    3. If auth is disabled (auth_service is None globally) -> return PUBLIC_GROUP
    4. Default: None (anonymous users cannot write when auth is enabled)
    
    Args:
        auth_tokens: Optional list of JWT tokens to extract write group from.
                    Uses the primary (first) group from the first valid token.
        auth_service: Optional AuthService for token validation.
                     Falls back to global GroupService's auth_service.
    
    Returns:
        Primary group name the caller can write to, or None if anonymous
        (when auth is enabled).
    """
    # If explicit tokens provided, extract write group from first valid token
    if auth_tokens:
        result = _extract_write_group_from_tokens(auth_tokens, auth_service)
        # If extraction failed but auth is disabled, allow public writes
        if result is None:
            if auth_service is None:
                try:
                    service = get_group_service()
                    if service.auth_service is None:
                        return PUBLIC_GROUP
                except RuntimeError:
                    return PUBLIC_GROUP
        return result
    
    # Otherwise, fall back to context-based extraction
    result = get_write_group_from_context(auth_service)
    
    # If result is None and auth is globally disabled, allow writes to public group
    if result is None:
        # Check if auth is globally disabled
        if auth_service is None:
            try:
                service = get_group_service()
                if service.auth_service is None:
                    # Auth is disabled, allow writes to public group
                    return PUBLIC_GROUP
            except RuntimeError:
                # No global service yet, assume auth disabled
                return PUBLIC_GROUP
    
    return result


def _extract_write_group_from_tokens(
    auth_tokens: list[str],
    auth_service: AuthService | None = None,
) -> str | None:
    """Extract primary write group name from the first valid JWT token.
    
    Args:
        auth_tokens: List of JWT tokens (without "Bearer " prefix)
        auth_service: Optional AuthService for token validation.
        
    Returns:
        Primary group name from the first valid token, or None.
    """
    # Get auth service if not provided
    if auth_service is None:
        try:
            service = get_group_service()
            auth_service = service.auth_service
        except RuntimeError:
            return None
    
    if auth_service is None:
        return None
    
    # Try each token until we find a valid one
    for token in auth_tokens:
        # Strip "Bearer " prefix if present (be lenient)
        if token.startswith("Bearer "):
            token = token[7:]
        
        try:
            # Vault backend requires store lookup (require_store=True)
            token_info = auth_service.verify_token(token, require_store=True)
            if token_info and token_info.groups:
                return token_info.groups[0]  # Return primary group name
        except Exception as e:  # nosec B110 - Intentionally continue on invalid tokens
            # Log and continue to next token
            from app.logger import session_logger
            session_logger.error(f"Token verification failed for token (truncated: {token[:20]}...): {e}", exc_info=True)
            pass
    
    return None


def get_group_uuid_by_name(
    group_name: str,
    auth_service: AuthService | None = None,
) -> str | None:
    """Convert a group name to its UUID.
    
    Use this function when you need a group UUID for data storage (e.g., Document.group_guid).
    This follows the design principle: "Group names flow through auth; UUIDs are resolved
    at point of use."
    
    Args:
        group_name: The group name (e.g., 'public', 'admin', 'premium')
        auth_service: Optional AuthService for group lookup.
                     Falls back to global GroupService's auth_service.
        
    Returns:
        The group UUID string, or None if the group doesn't exist.
        
    Example:
        >>> write_group_name = resolve_write_group(auth_tokens)  # "premium"
        >>> group_uuid = get_group_uuid_by_name(write_group_name)
        >>> source = Source(group_guid=group_uuid, ...)
    """
    # Get auth service if not provided
    if auth_service is None:
        try:
            service = get_group_service()
            auth_service = service.auth_service
        except RuntimeError:
            return None
    
    if auth_service is None:
        return None
    
    try:
        group = auth_service.groups.get_group_by_name(group_name)
        if group:
            return str(group.id)
    except Exception:  # nosec B110 - Group lookup may fail for various reasons
        pass
    
    return None


def get_group_uuids_by_names(
    group_names: list[str],
    auth_service: AuthService | None = None,
) -> list[str]:
    """Convert a list of group names to their UUIDs.
    
    Use this function when you need group UUIDs for data access filtering.
    Skips any groups that don't exist (no error raised).
    
    Args:
        group_names: List of group names (e.g., ['public', 'admin', 'premium'])
        auth_service: Optional AuthService for group lookup.
                     Falls back to global GroupService's auth_service.
        
    Returns:
        List of group UUID strings for groups that exist.
        
    Example:
        >>> group_names = resolve_permitted_groups(auth_tokens)  # ["admin", "public"]
        >>> group_uuids = get_group_uuids_by_names(group_names)
        >>> sources = source_registry.list_sources(access_groups=group_uuids)
    """
    uuids = []
    for name in group_names:
        uuid = get_group_uuid_by_name(name, auth_service)
        if uuid:
            uuids.append(uuid)
    return uuids


# =============================================================================
# Admin Access Control
# =============================================================================


class AdminAccessDeniedError(Exception):
    """Raised when admin access is required but not present."""

    def __init__(self, message: str | None = None) -> None:
        msg = message or "Admin access required for this operation"
        super().__init__(msg)


def is_admin(
    auth_tokens: list[str] | None = None,
    auth_service: AuthService | None = None,
) -> bool:
    """Check if the caller has admin access.
    
    Checks if "admin" is in the caller's permitted groups.
    
    Args:
        auth_tokens: Optional list of JWT tokens to check.
                    If not provided, checks the request context.
        auth_service: Optional AuthService for token validation.
                     Falls back to global GroupService's auth_service.
    
    Returns:
        True if caller has admin access, False otherwise.
    """
    groups = resolve_permitted_groups(auth_tokens, auth_service)
    return "admin" in groups


def require_admin(
    auth_tokens: list[str] | None = None,
    auth_service: AuthService | None = None,
) -> None:
    """Require admin access or raise an error.
    
    Use this function at the start of any operation that requires
    admin privileges (e.g., creating groups, tokens, or sources).
    
    Args:
        auth_tokens: Optional list of JWT tokens to check.
                    If not provided, checks the request context.
        auth_service: Optional AuthService for token validation.
                     Falls back to global GroupService's auth_service.
    
    Raises:
        AdminAccessDeniedError: If admin access is not present.
    
    Example:
        >>> @mcp.tool(name="create_source")
        >>> def create_source(name: str, auth_tokens: list[str] | None = None):
        >>>     require_admin(auth_tokens)
        >>>     # ... create source logic
    """
    if not is_admin(auth_tokens, auth_service):
        raise AdminAccessDeniedError(
            "Admin access required for this operation. "
            "Use a token with 'admin' group membership."
        )
