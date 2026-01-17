# Step 7: Group/Token Management in gofr-common - Verification

**Date**: 2026-01-12  
**Status**: ✅ COMPLETE  
**Location**: `lib/gofr-common/src/gofr_common/auth/`

## Overview

Step 7 verifies that the gofr-common authentication library has proper infrastructure and tests for group/token management. The admin-only enforcement is handled at the **MCP tool level in gofr-iq**, not in gofr-common itself.

## Design Philosophy

- **gofr-common**: Provides infrastructure (GroupRegistry, AuthService) without business logic enforcement
- **gofr-iq**: Enforces admin-only rules via `require_admin()` at the MCP tool level
- **Separation of Concerns**: Infrastructure (gofr-common) vs Policy Enforcement (gofr-iq)

## Requirements from Design Document

### Requirement 1: GroupRegistry has proper admin checks if exposed via API

**Status**: ✅ **Not applicable** - GroupRegistry is not exposed via API in gofr-common

**Details**:
- GroupRegistry is an internal infrastructure component
- API-level admin checks are enforced in gofr-iq via `require_admin()` before calling GroupRegistry methods
- Reserved groups (admin, public) cannot be deleted - enforced at GroupRegistry level
- This architectural decision keeps gofr-common reusable across projects

### Requirement 2: Token creation in AuthService includes group validation

**Status**: ✅ **COMPLETE** - Fully implemented and tested

**Implementation**:
- Location: `lib/gofr-common/src/gofr_common/auth/service.py`
- Method: `AuthService.create_token(groups: List[str])`
- Validation: Raises `InvalidGroupError` if any group doesn't exist
- Test: `test_create_token_invalid_group` in `tests/test_auth.py`

**Code Reference**:
```python
def create_token(self, groups: List[str], ...) -> str:
    # Validate all groups exist
    for group_name in groups:
        if not self.groups.get_group_by_name(group_name):
            raise InvalidGroupError(f"Group '{group_name}' does not exist")
    ...
```

## Test Coverage

### GroupRegistry Tests (`tests/test_groups.py`)

**Total Tests**: 40 ✅ All passing

#### Reserved Group Protection
- ✅ `test_reserved_groups_created` - Reserved groups auto-created on init
- ✅ `test_make_defunct_reserved_raises` - Cannot delete 'public' group
- ✅ `test_make_defunct_admin_reserved_raises` - Cannot delete 'admin' group
- ✅ `test_create_group_reserved_name_raises` - Cannot create group named 'public'
- ✅ `test_create_group_reserved_name_admin_raises` - Cannot create group named 'admin'
- ✅ `test_reserved_group_case_insensitive_check` - Case-insensitive protection

#### Group Lifecycle
- ✅ `test_create_group` - Create new group with description
- ✅ `test_create_group_without_description` - Create minimal group
- ✅ `test_create_group_duplicate_raises` - Prevent duplicate group names
- ✅ `test_get_group_by_id` - Retrieve group by UUID
- ✅ `test_get_group_by_name` - Retrieve group by name
- ✅ `test_list_groups` - List all active groups
- ✅ `test_list_groups_excludes_defunct` - Soft-delete filtering
- ✅ `test_list_groups_include_defunct` - Include deleted groups optionally
- ✅ `test_make_defunct` - Soft-delete group
- ✅ `test_make_defunct_already_defunct` - Idempotent deletion

#### Storage Backends
- ✅ `TestGroupRegistryInMemory` - In-memory storage (7 tests)
- ✅ `TestGroupRegistryFileBased` - File-based persistence (6 tests)
- ✅ `test_registry_persists_changes` - Changes survive reload
- ✅ `test_ensure_reserved_groups_idempotent` - Bootstrap is safe to repeat

#### Edge Cases
- ✅ `test_group_name_case_sensitivity` - Names are case-sensitive
- ✅ `test_many_groups` - Scale test (100 groups)
- ✅ `test_defunct_group_still_retrievable` - Soft-delete preserves data
- ✅ `test_group_roundtrip` - Serialization/deserialization

### AuthService Tests (`tests/test_auth.py`)

**Total Tests**: 73 ✅ All passing

#### Token Creation with Group Validation
- ✅ `test_create_token` - Basic token creation with admin group
- ✅ `test_create_token_multiple_groups` - Multiple group membership
- ✅ `test_create_token_invalid_group` - **Rejects non-existent groups**
- ✅ `test_create_token_with_expiry` - Custom TTL
- ✅ `test_create_token_with_fingerprint` - Device binding
- ✅ `test_create_token_saves_to_file` - Persistence

#### Token Verification
- ✅ `test_verify_valid_token` - JWT validation
- ✅ `test_verify_token_multiple_groups` - Group extraction
- ✅ `test_verify_expired_token` - Expiry enforcement
- ✅ `test_verify_token_not_in_store` - Revocation check
- ✅ `test_verify_token_wrong_secret` - Security validation
- ✅ `test_verify_token_fingerprint_mismatch` - Device binding check

#### Token Lifecycle
- ✅ `test_revoke_token` - Soft-delete token
- ✅ `test_revoke_token_prevents_verification` - Revoked tokens rejected
- ✅ `test_list_tokens` - List all tokens
- ✅ `test_list_tokens_status_filter` - Filter by active/revoked

#### Group Resolution
- ✅ `test_resolve_token_groups` - Extract groups from JWT
- ✅ `test_resolve_token_always_includes_public` - Public group auto-added
- ✅ `test_resolve_token_groups_for_invalid_token` - Graceful failure

#### Authorization Helpers
- ✅ `test_require_admin_is_callable` - Admin guard available
- ✅ `test_token_info_has_group` - Group membership check
- ✅ `test_token_info_has_any_group` - OR group check
- ✅ `test_token_info_has_all_groups` - AND group check

## Admin-Only Enforcement Architecture

### In gofr-common (Infrastructure)
```python
# GroupRegistry - Enforces reserved group protection
def make_defunct(self, group_id: UUID) -> bool:
    group = self.get_group(group_id)
    if group.is_reserved:
        raise ReservedGroupError(f"Cannot make reserved group defunct: {group.name}")
    ...

# AuthService - Enforces group existence
def create_token(self, groups: List[str]) -> str:
    for group_name in groups:
        if not self.groups.get_group_by_name(group_name):
            raise InvalidGroupError(f"Group '{group_name}' does not exist")
    ...
```

### In gofr-iq (Policy Enforcement)
```python
# app/services/group_service.py - Admin authorization
def is_admin(auth_tokens: list[str] | None) -> bool:
    """Check if any token has admin group membership."""
    if not auth_tokens:
        return False
    for token in auth_tokens:
        info = vault_auth_service.verify_token(token)
        if ADMIN_GROUP in info.groups:
            return True
    return False

def require_admin(auth_tokens: list[str] | None) -> None:
    """Raise AdminAccessDeniedError if not admin."""
    if not is_admin(auth_tokens):
        raise AdminAccessDeniedError(
            "Admin access required for this operation"
        )

# app/tools/source_tools.py - MCP tool enforcement
@mcp.tool(name="create_source")
def create_source(auth_tokens: list[str] | None = None) -> ToolResponse:
    require_admin(auth_tokens)  # ← Admin check BEFORE operation
    source = source_registry.create(...)
    ...
```

## Why gofr-common Doesn't Enforce Admin-Only Rules

1. **Reusability**: gofr-common is used by multiple projects with different authorization models
2. **Separation of Concerns**: Infrastructure (data access) vs Policy (who can do what)
3. **Flexibility**: Different projects can have different admin group names
4. **Testing**: Easier to test infrastructure separately from policy
5. **Explicitness**: Policy enforcement is visible at the API/tool level

## Integration with gofr-iq

The admin access control flow:

```
User Request (MCP Client)
    ↓
MCP Tool (app/tools/source_tools.py)
    ↓
require_admin(auth_tokens)  ← Policy Enforcement (gofr-iq)
    ↓
is_admin() → verify_token() → AuthService (gofr-common)
    ↓
GroupRegistry Operations (gofr-common)  ← Infrastructure
```

## Conclusion

**Step 7 Status**: ✅ **COMPLETE**

All requirements are satisfied:
- ✅ GroupRegistry has proper reserved group protection (not exposed via API)
- ✅ AuthService validates group existence during token creation
- ✅ 40 passing tests for GroupRegistry
- ✅ 73 passing tests for AuthService
- ✅ Admin-only enforcement correctly placed at MCP tool level in gofr-iq

The separation between infrastructure (gofr-common) and policy enforcement (gofr-iq) is working as designed.

## Next Steps

Proceed to **Step 8**: Update integration tests in gofr-iq to reflect:
- Sources are global (no group_guid)
- Admin-only source management
- Bootstrap token flow
