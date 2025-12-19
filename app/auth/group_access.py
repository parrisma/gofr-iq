"""Group Access Control for APAC Brokerage News Repository.

This module provides group-based access control with:
- Token group extraction from JWT (multi-group support via auth v2)
- Group membership validation
- Permission checking (read/write/admin equivalents)
- Integration with document store for access enforcement
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from gofr_common.auth import AuthService, TokenInfo

from app.models import Permission


class AccessLevel(str, Enum):
    """Access level abstraction over Permission combinations.
    
    Maps to underlying Permission enum:
    - READ: Permission.READ only
    - WRITE: Permission.READ + Permission.CREATE + Permission.UPDATE
    - ADMIN: All permissions (READ + CREATE + UPDATE + DELETE)
    """
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"

    @property
    def required_permissions(self) -> list[Permission]:
        """Get the permissions required for this access level."""
        if self == AccessLevel.READ:
            return [Permission.READ]
        elif self == AccessLevel.WRITE:
            return [Permission.READ, Permission.CREATE, Permission.UPDATE]
        else:  # ADMIN
            return [Permission.READ, Permission.CREATE, Permission.UPDATE, Permission.DELETE]


class GroupAccessError(Exception):
    """Base exception for group access errors."""

    pass


class GroupNotFoundError(GroupAccessError):
    """Raised when a group is not found."""

    def __init__(self, group_guid: str) -> None:
        self.group_guid = group_guid
        super().__init__(f"Group not found: {group_guid}")


class AccessDeniedError(GroupAccessError):
    """Raised when access to a group is denied."""

    def __init__(
        self,
        group_guid: str,
        required_permission: Permission | None = None,
        reason: str | None = None,
    ) -> None:
        self.group_guid = group_guid
        self.required_permission = required_permission
        self.reason = reason
        
        msg = f"Access denied to group {group_guid}"
        if required_permission:
            msg += f" (requires {required_permission.value})"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class TokenValidationError(GroupAccessError):
    """Raised when token validation fails."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Token validation failed: {reason}")


@dataclass
class GroupClaims:
    """Claims extracted from a JWT token for group access.
    
    Attributes:
        token_id: The unique token identifier
        groups: List of group GUIDs the token has access to
        primary_group: The primary/default group for the token
        issued_at: When the token was issued
        expires_at: When the token expires (None if no expiry)
    """
    token_id: str
    groups: list[str]
    primary_group: str
    issued_at: datetime
    expires_at: datetime | None

    def has_group(self, group_guid: str) -> bool:
        """Check if the token has access to a specific group."""
        return group_guid in self.groups


class GroupAccessService:
    """Service for group-based access control.
    
    This service bridges JWT token validation with group-based permissions.
    It extracts group claims from tokens and checks permissions against
    group configurations.
    
    Attributes:
        auth_service: The underlying JWT authentication service
        group_store: Optional store for group configurations
    """

    def __init__(
        self,
        auth_service: AuthService,
        group_store: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the group access service.
        
        Args:
            auth_service: JWT authentication service instance
            group_store: Optional mapping of group_guid to group config.
                        Group config should contain 'tokens' dict mapping
                        token_id to list of permission strings.
        """
        self.auth_service = auth_service
        self.group_store = group_store or {}

    def extract_groups_from_token(self, token: str) -> GroupClaims:
        """Extract group claims from a JWT token.
        
        Uses auth v2 multi-group tokens. Returns all groups from the token
        plus the public group.
        
        Args:
            token: JWT token string
            
        Returns:
            GroupClaims with extracted group information
            
        Raises:
            TokenValidationError: If token is invalid or missing group claims
        """
        try:
            token_info: TokenInfo = self.auth_service.verify_token(token)
            
            # v2: Token contains multiple groups
            # Primary group is the first group in the list
            groups = list(token_info.groups)
            primary_group = groups[0] if groups else "public"
            
            # Always include public group
            if "public" not in groups:
                groups.append("public")
            
            return GroupClaims(
                token_id=token_info.token,
                groups=groups,
                primary_group=primary_group,
                issued_at=token_info.issued_at,
                expires_at=token_info.expires_at,
            )
        except ValueError as e:
            raise TokenValidationError(str(e)) from e

    def validate_group_membership(
        self,
        token: str,
        group_guid: str,
    ) -> GroupClaims:
        """Validate that a token has access to a specific group.
        
        Access is determined by:
        1. If no group_store, token's primary group must match group_guid
        2. If group_store exists, check if token's group is in the group's tokens mapping
        
        Args:
            token: JWT token string
            group_guid: Group GUID to check access for
            
        Returns:
            GroupClaims if access is granted
            
        Raises:
            TokenValidationError: If token is invalid
            AccessDeniedError: If token doesn't have access to the group
        """
        claims = self.extract_groups_from_token(token)
        
        # If no group store, use simple group name matching
        if not self.group_store:
            if not claims.has_group(group_guid):
                raise AccessDeniedError(
                    group_guid=group_guid,
                    reason=f"Token does not have access to group {group_guid}",
                )
            return claims
        
        # Check if the group exists in store
        if group_guid not in self.group_store:
            raise GroupNotFoundError(group_guid)
        
        # Check if token's group is in the group's tokens mapping
        group_config = self.group_store[group_guid]
        tokens_config = group_config.get("tokens", {})
        
        # Token has access if its primary_group is in the tokens mapping
        if claims.primary_group in tokens_config:
            return claims
        
        raise AccessDeniedError(
            group_guid=group_guid,
            reason=f"Token group '{claims.primary_group}' not authorized for group {group_guid}",
        )

    def check_permission(
        self,
        token: str,
        group_guid: str,
        permission: Permission,
    ) -> GroupClaims:
        """Check if a token has a specific permission on a group.
        
        This method validates:
        1. Token is valid
        2. Token has access to the group
        3. Token has the required permission on the group
        
        Args:
            token: JWT token string
            group_guid: Group GUID to check permission on
            permission: Required permission
            
        Returns:
            GroupClaims if permission is granted
            
        Raises:
            TokenValidationError: If token is invalid
            AccessDeniedError: If token doesn't have required permission
            GroupNotFoundError: If group is not in group_store
        """
        # First validate group membership (also checks group exists in store)
        claims = self.validate_group_membership(token, group_guid)
        
        # If no group store, assume full access (for testing/admin scenarios)
        if not self.group_store:
            return claims
        
        group_config = self.group_store[group_guid]
        tokens_config = group_config.get("tokens", {})
        
        # Get permissions for this token's group
        token_permissions = tokens_config.get(claims.primary_group, [])
        
        # Convert string permissions to enum if needed
        permission_values = [
            Permission(p) if isinstance(p, str) else p
            for p in token_permissions
        ]
        
        if permission not in permission_values:
            raise AccessDeniedError(
                group_guid=group_guid,
                required_permission=permission,
                reason="Token missing required permission",
            )
        
        return claims

    def check_access_level(
        self,
        token: str,
        group_guid: str,
        access_level: AccessLevel,
    ) -> GroupClaims:
        """Check if a token has an access level on a group.
        
        Access levels map to permission combinations:
        - READ: Requires Permission.READ
        - WRITE: Requires Permission.READ, CREATE, UPDATE  
        - ADMIN: Requires all permissions
        
        Args:
            token: JWT token string
            group_guid: Group GUID to check
            access_level: Required access level
            
        Returns:
            GroupClaims if access level is granted
            
        Raises:
            TokenValidationError: If token is invalid
            AccessDeniedError: If token doesn't have required access level
        """
        # First validate group membership (also validates group exists)
        claims = self.validate_group_membership(token, group_guid)
        
        # If no group store, assume full access
        if not self.group_store:
            return claims
        
        group_config = self.group_store[group_guid]
        tokens_config = group_config.get("tokens", {})
        
        # Get token's permissions by primary group
        token_permissions = tokens_config.get(claims.primary_group, [])
        
        # Convert to Permission enums
        permission_values = set(
            Permission(p) if isinstance(p, str) else p
            for p in token_permissions
        )
        
        # Check if all required permissions are present
        required = set(access_level.required_permissions)
        if not required.issubset(permission_values):
            missing = required - permission_values
            raise AccessDeniedError(
                group_guid=group_guid,
                reason=f"Missing permissions for {access_level.value}: {[p.value for p in missing]}",
            )
        
        return claims

    def get_accessible_groups(self, token: str) -> list[str]:
        """Get list of group GUIDs a token has access to.
        
        Args:
            token: JWT token string
            
        Returns:
            List of group GUIDs
            
        Raises:
            TokenValidationError: If token is invalid
        """
        claims = self.extract_groups_from_token(token)
        return claims.groups
