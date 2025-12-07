"""Group and token permission models.

Groups define isolation boundaries and token permissions. Each group
has a unique GUID and contains documents and sources. Access control
is managed through token permissions per group.

Schema from IMPLEMENTATION.md Section 3.3.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator


class Permission(str, Enum):
    """Valid permission levels for token access.
    
    Permissions control what operations a token can perform within a group:
    - create: Ingest documents, register sources
    - read: Query documents, view sources
    - update: Update document metadata, update sources
    - delete: Soft-delete documents and sources
    """
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


# Type alias for token permissions mapping
TokenPermissions = dict[str, list[Permission]]


class GroupMetadata(BaseModel):
    """Optional metadata for a group.
    
    Attributes:
        region: Geographic region (e.g., "APAC", "Global")
        department: Organizational department
        Additional fields can be added as needed.
    """
    region: str | None = None
    department: str | None = None
    
    model_config = {"extra": "allow"}


class Group(BaseModel):
    """Group model representing an isolation boundary for documents and sources.
    
    Groups are the primary access control boundary. Each document and source
    belongs to exactly one group. Tokens are granted permissions per group.
    
    Attributes:
        group_guid: Unique identifier for the group (UUID format)
        name: Human-readable group name
        description: Optional group description
        created_at: When the group was created
        updated_at: When the group was last updated
        active: Whether the group is active (soft delete support)
        tokens: Mapping of token_id to list of permissions
        metadata: Optional additional group metadata
    
    Example:
        >>> group = Group(
        ...     group_guid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        ...     name="APAC Research",
        ...     description="Asia-Pacific research documents",
        ...     tokens={
        ...         "token_001": [Permission.CREATE, Permission.READ],
        ...         "token_002": [Permission.READ],
        ...     }
        ... )
    """
    group_guid: Annotated[str, Field(
        min_length=36,
        max_length=36,
        pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
        description="UUID format group identifier",
    )]
    name: Annotated[str, Field(
        min_length=1,
        max_length=255,
        description="Human-readable group name",
    )]
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional group description",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the group was created",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the group was last updated",
    )
    active: bool = Field(
        default=True,
        description="Whether the group is active",
    )
    tokens: dict[str, list[Permission]] = Field(
        default_factory=dict,
        description="Mapping of token_id to permissions",
    )
    metadata: GroupMetadata | None = Field(
        default=None,
        description="Optional additional metadata",
    )
    
    @field_validator("tokens", mode="before")
    @classmethod
    def validate_tokens(cls, v: Any) -> dict[str, list[Permission]]:
        """Convert string permissions to Permission enum."""
        if not isinstance(v, dict):
            return v
        
        result: dict[str, list[Permission]] = {}
        for token_id, perms in v.items():
            if isinstance(perms, list):
                result[token_id] = [
                    Permission(p) if isinstance(p, str) else p
                    for p in perms
                ]
            else:
                result[token_id] = perms
        return result
    
    def has_permission(self, token_id: str, permission: Permission) -> bool:
        """Check if a token has a specific permission on this group.
        
        Args:
            token_id: The token identifier to check.
            permission: The permission to check for.
        
        Returns:
            True if the token has the permission, False otherwise.
        """
        if token_id not in self.tokens:
            return False
        return permission in self.tokens[token_id]
    
    def get_permissions(self, token_id: str) -> list[Permission]:
        """Get all permissions for a token on this group.
        
        Args:
            token_id: The token identifier.
        
        Returns:
            List of permissions (empty if token not found).
        """
        return self.tokens.get(token_id, [])
    
    def add_token(
        self,
        token_id: str,
        permissions: list[Permission],
    ) -> None:
        """Add or update a token's permissions.
        
        Args:
            token_id: The token identifier.
            permissions: List of permissions to grant.
        """
        self.tokens[token_id] = permissions
        self.updated_at = datetime.utcnow()
    
    def remove_token(self, token_id: str) -> bool:
        """Remove a token's access to this group.
        
        Args:
            token_id: The token identifier.
        
        Returns:
            True if token was removed, False if not found.
        """
        if token_id in self.tokens:
            del self.tokens[token_id]
            self.updated_at = datetime.utcnow()
            return True
        return False
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "group_guid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "name": "APAC Research",
                "description": "Asia-Pacific research team documents",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-12-08T00:00:00Z",
                "active": True,
                "tokens": {
                    "token_001": ["create", "read", "update", "delete"],
                    "token_002": ["read"],
                },
                "metadata": {
                    "region": "APAC",
                    "department": "Research",
                },
            }
        }
    }
