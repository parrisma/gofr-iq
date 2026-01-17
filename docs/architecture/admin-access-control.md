# Admin Access Control Design

**Status**: ✅ Implementation Complete (Steps 1-10)  
**Date**: January 12, 2026

## Implementation Progress

- ✅ **Step 1**: Admin guard helper (12 tests passing)
- ✅ **Step 2**: Admin enforcement in source tools (16 tests passing)
- ✅ **Step 3**: Decouple sources from groups (35 tests passing)
- ✅ **Step 4**: Update ingestion validation (29 tests passing)
- ✅ **Step 5**: Update MCP ingest tools (15 tests passing)
- ✅ **Step 6**: Bootstrap documentation and verification (9 tests passing)
- ✅ **Step 7**: Group/token management tools - gofr-common verification (113 tests passing)
- ✅ **Step 8**: Update integration tests (57 tests passing)
- ✅ **Step 9**: Update documentation (7 files updated)
- ✅ **Step 10**: Final validation (1323+ tests passing)

**Total Tests**: 1323+ passing (gofr-common: 621, gofr-iq: 702)

**Known Issues**:
- LLM integration tests: 15 failures (OpenRouter API authentication - infrastructure issue)
- Code quality: Pre-existing linting warnings (whitespace - W293)
- gofr-common: 1 CLI test cleanup issue (non-blocking)

**Breaking Changes**:
- Sources no longer have `group_guid` field (global entities)
- Migration: Delete `data/auth/sources/` directory before deployment
- Bootstrap: Admin token creation required via Vault root token

---

## Overview

This document defines the access control model for administrative operations in GOFR-IQ. It covers:

1. **What requires admin access**: Groups, Tokens, Sources management
2. **Bootstrap mechanism**: How to create the first admin token
3. **Runtime enforcement**: How admin checks are performed
4. **Separation of concerns**: CLI vs API access

---

## 1. Access Control Model

### 1.1 Protected Resources

| Resource      | Create        | Read | Update | Delete |
|-------------- |---------------|------|--------|--------|
| **Groups**    | admin         | any | admin | admin |
| **Tokens**    | admin         | admin | admin | admin |
| **Sources**   | admin         | any | admin | admin |
| **Documents** | authenticated | group-filtered | authenticated | authenticated |

**Key Principle**: Sources are standalone entities (completely independent of groups). They track attribution (where content came from), trust level, and metadata. Any authenticated user can ingest documents referencing any source. Only admins can create/modify sources.

### 1.2 Two Access Tiers

```
┌─────────────────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE TIER                          │
│         (CLI tools with direct backend access)                  │
│                                                                 │
│  ┌─────────────────┐    ┌─────────────────┐                    │
│  │ auth_manager.sh │───▶│  Vault Backend  │                    │
│  └─────────────────┘    └─────────────────┘                    │
│           │                                                     │
│           │ Uses: GOFR_VAULT_TOKEN (root token)                │
│           │ Purpose: Bootstrap, disaster recovery               │
│           │ Access: Operators with server access                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Creates admin JWT
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    APPLICATION TIER                             │
│         (API/MCP with JWT authentication)                       │
│                                                                 │
│  ┌─────────────────┐    ┌─────────────────┐                    │
│  │   MCP Server    │───▶│  JWT Validation │                    │
│  │   Web Server    │    └─────────────────┘                    │
│  │   MCPO Server   │            │                              │
│  └─────────────────┘            ▼                              │
│                         ┌─────────────────┐                    │
│                         │ Admin Check:    │                    │
│                         │ "admin" ∈ groups│                    │
│                         └─────────────────┘                    │
│                                                                 │
│  Access: API clients with JWT tokens                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Bootstrap Mechanism

### 2.1 The Bootstrap Problem

At system initialization:
- Reserved groups (`admin`, `public`) exist automatically
- No tokens exist yet
- Cannot create tokens via API (requires admin token)
- Need a way to create the first admin token

### 2.2 Solution: CLI Bootstrap

The `auth_manager.sh` CLI tool provides bootstrap capability:

```bash
# Infrastructure operator runs this on the server
lib/gofr-common/scripts/auth_manager.sh --docker tokens create --groups admin
```

**Why this works:**
1. CLI uses **Vault root token** (infrastructure credential), not JWT
2. Vault root token is set via environment variable (`GOFR_VAULT_TOKEN`)
3. This is a deliberate separation: infrastructure vs application credentials
4. Only operators with server/container access can bootstrap

### 2.3 Bootstrap Sequence

```
┌─────────────────────────────────────────────────────────────────┐
│                    BOOTSTRAP SEQUENCE                           │
└─────────────────────────────────────────────────────────────────┘

Step 1: System Start
├── Vault initializes
├── Reserved groups created: [admin, public]
└── No tokens exist

Step 2: Operator Bootstrap (one-time)
├── Operator runs: auth_manager.sh tokens create --groups admin
├── CLI authenticates to Vault using GOFR_VAULT_TOKEN
├── Vault creates token record
└── JWT returned to operator

Step 3: Admin Token Distribution
├── Operator stores admin JWT securely
├── Admin JWT used for API management operations
└── System is now bootstrapped

Step 4: Normal Operations
├── Admin creates additional groups via API
├── Admin creates user tokens via API
├── Admin creates sources via API
└── Users ingest/query documents via API
```

### 2.4 Security Considerations

| Credential | Scope | Storage | Who Has Access |
|------------|-------|---------|----------------|
| Vault Root Token | Infrastructure | Environment variable | Operators only |
| Admin JWT | Application | Secure storage | Admins only |
| User JWT | Application | Client storage | End users |

**Important**: The Vault root token should NEVER be exposed to application code or APIs. It is strictly for infrastructure management.

---

## 3. Runtime Enforcement

### 3.1 Admin Check Implementation

All protected operations check for admin group membership:

```python
def require_admin(auth_tokens: list[str] | None) -> None:
    """Raise error if caller doesn't have admin access.
    
    Args:
        auth_tokens: JWT tokens from request
        
    Raises:
        PermissionError: If admin group not in token
    """
    groups = resolve_permitted_groups(auth_tokens)
    if "admin" not in groups:
        raise PermissionError("Admin access required")
```

### 3.2 Tool-Level Enforcement

Each protected MCP tool includes admin check:

```python
@mcp.tool(name="create_group")
def create_group(name: str, auth_tokens: list[str] | None = None):
    """Create a new group. ADMIN ONLY."""
    require_admin(auth_tokens)
    # ... implementation
```

### 3.3 Error Responses

When admin access is denied:

```json
{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "Admin access required for this operation",
    "recovery_strategy": "Use a token with admin group membership"
  }
}
```

---

## 4. API Operations by Access Level

### 4.1 Admin-Only Operations (MCP Tools)

| Tool | Description |
|------|-------------|
| `create_group` | Create a new group |
| `update_group` | Update group metadata |
| `delete_group` | Soft-delete a group |
| `create_token` | Create a new JWT token |
| `revoke_token` | Revoke an existing token |
| `list_tokens` | List all tokens |
| `create_source` | Register a new source |
| `update_source` | Update source metadata |
| `delete_source` | Soft-delete a source |

### 4.2 Authenticated Operations

| Tool | Description |
|------|-------------|
| `ingest_document` | Ingest document (to caller's group) |
| `update_document` | Update document metadata |
| `delete_document` | Soft-delete document |

### 4.3 Group-Filtered Operations (Read)

| Tool | Description |
|------|-------------|
| `query_documents` | Search documents (filtered by caller's groups) |
| `get_document` | Retrieve document (if in caller's groups) |
| `list_sources` | List all sources (global, no filter) |
| `get_source` | Get source details (global, no filter) |
| `list_groups` | List groups (optionally all for admin) |

---

## 5. Group and Token Lifecycle

### 5.1 Reserved Groups

Two groups are reserved and cannot be deleted:

| Group | Purpose |
|-------|---------|
| `admin` | System administrators - can manage all resources |
| `public` | Default group for public/unauthenticated access |

### 5.2 Token Lifecycle

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Created    │────▶│    Active    │────▶│   Revoked    │
│  (via CLI    │     │  (valid for  │     │  (cannot be  │
│   or API)    │     │   requests)  │     │    used)     │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   Expired    │
                     │  (past TTL)  │
                     └──────────────┘
```

### 5.3 Group Membership in Tokens

A token's `groups` claim determines access:

```json
{
  "jti": "token-uuid",
  "groups": ["admin", "apac-sales"],
  "iat": 1768145000,
  "exp": 1775921000
}
```

- Token has access to resources in `admin` and `apac-sales` groups
- Token can perform admin operations (has `admin`)
- Token can read documents in both groups

---

## 6. Source Management

### 6.1 Sources Are Standalone Entities

Sources are **completely independent** of groups. They are global metadata entities that track:
- **Attribution**: Where the content originated (e.g., "Reuters", "Bloomberg")
- **Trust Level**: Credibility scoring (verified, trusted, standard, unverified)
- **Metadata**: Source type, region, languages, boost factors

This means:
- Sources exist in a flat global namespace
- Any source can be referenced when ingesting to any group
- Groups control document access ("who can read this document")
- Sources control attribution and trust scoring ("where did this come from")

### 6.2 Source Lifecycle

```
┌──────────────────────────────────────────────────────────────┐
│                    SOURCE USAGE                              │
└──────────────────────────────────────────────────────────────┘

Admin creates source:
  create_source(name="Reuters", type="news_agency")
  → Returns source_guid

Any user ingests document:
  ingest_document(
    title="...",
    content="...",
    source_guid="reuters-uuid",   # References global source
    # group determined by token
  )
  → Document stored in user's group
  → Document references Reuters source
```

### 6.3 Storage Structure

```
data/storage/
├── sources/                    # Global sources (flat, no groups)
│   ├── {source_guid_1}.json   # Reuters
│   ├── {source_guid_2}.json   # Bloomberg
│   ├── {source_guid_3}.json   # TechCrunch
│   └── ...                    # All sources in single directory
│
├── documents/                  # Documents organized by group
│   ├── {group_guid_public}/
│   │   ├── {doc_guid_1}.json  # May reference any source
│   │   └── ...
│   ├── {group_guid_sales}/
│   │   ├── {doc_guid_5}.json  # May reference any source
│   │   └── ...
│   └── ...
│
└── audit/
    ├── sources/               # Source audit logs (admin actions)
    └── documents/             # Document audit logs
```

**Key Point**: Sources directory is flat with no group subdirectories. Documents directory is organized by group for access control.

---

## 7. CLI Reference

### 7.1 Bootstrap Commands

```bash
# Create first admin token (run once during setup)
auth_manager.sh --docker tokens create --groups admin --expires 31536000

# Create token with multiple groups
auth_manager.sh --docker tokens create --groups admin,apac-sales

# List all tokens (for audit)
auth_manager.sh --docker tokens list

# Revoke a compromised token
auth_manager.sh --docker tokens revoke <token-id>
```

### 7.2 Group Management (CLI)

```bash
# List groups
auth_manager.sh --docker groups list

# Create custom group
auth_manager.sh --docker groups create <name> --description "..."

# Make group defunct
auth_manager.sh --docker groups defunct <name>
```

### 7.3 When to Use CLI vs API

| Use CLI When | Use API When |
|--------------|--------------|
| Initial bootstrap | Normal operations |
| Disaster recovery | User self-service (if enabled) |
| Emergency token revocation | Application-level admin |
| Direct backend access needed | Standard authenticated requests |

---

## 8. Security Best Practices

### 8.1 Credential Rotation

| Credential | Rotation Frequency | Method |
|------------|-------------------|--------|
| Vault Root Token | Annually or on compromise | Vault rekey |
| Admin JWT | Quarterly | Create new, revoke old |
| User JWT | Monthly or per-session | Application handles |

### 8.2 Admin Token Protection

1. **Never log admin tokens** - Mask in all logs
2. **Short expiry** - 90 days max for admin tokens
3. **Secure storage** - Use secrets manager (not .env files)
4. **Audit trail** - Log all admin operations
5. **Least privilege** - Create separate tokens for different admin tasks

### 8.3 Bootstrap Security

1. **One-time bootstrap** - Document when bootstrap occurred
2. **Secure channel** - Run CLI on server, not remotely
3. **Immediate storage** - Store generated token securely immediately
4. **Verification** - Test admin token before storing

---

## 9. Migration Notes

### 9.1 Existing Systems

If migrating from group-linked sources to standalone sources:

1. **Flatten source storage**: Move all sources from `sources/{group_guid}/{source_guid}.json` to `sources/{source_guid}.json`
2. **Remove group_guid field**: Update source records to remove or null out `group_guid` field
3. **Update access checks**: Remove group-based access validation for sources (they're now global)
4. **Update tests**: Remove tests that depend on source-group relationships
5. **Deploy with admin checks**: Ensure admin enforcement is in place before deployment

### 9.2 Source Model Changes

Before:
```json
{
  "source_guid": "abc-123",
  "group_guid": "group-xyz",  // REMOVED
  "name": "Reuters",
  "trust_level": "verified"
}
```

After:
```json
{
  "source_guid": "abc-123",
  "name": "Reuters",
  "trust_level": "verified",
  "type": "news_agency",
  "region": "Global",
  "languages": ["en"]
  // No group_guid - sources are standalone
}
```

### 9.3 Backward Compatibility

During transition:
- API may accept `group_guid` in source create/update operations but ignores it
- Responses omit `group_guid` field entirely (not even null)
- Log deprecation warnings if clients pass group_guid for sources

---

## 10. Summary

| Concept | Implementation |
|---------|----------------|
| Bootstrap | CLI with Vault root token creates first admin JWT |
| Admin check | Token must have "admin" in groups claim |
| Sources | Standalone entities (no group link), admin-only management |
| Groups | admin/public reserved, others created by admin |
| Tokens | Created via CLI (bootstrap) or API (runtime) |
| Documents | Group-bound for read access, can reference any source |

---

## 11. Implementation Plan (numbered)

### Step 1: Add admin guard helper
**Location**: `app/services/group_service.py` (gofr-iq)

- Implement `require_admin(auth_tokens: list[str] | None) -> None` helper function
- Use existing `resolve_permitted_groups(auth_tokens)` to get group list
- Raise `PermissionError` with clear message if "admin" not in groups
- Return appropriate error responses for MCP/API tools

**Tests** (gofr-iq):
- `test/test_group_service.py`: Add `test_require_admin_success()` and `test_require_admin_denied()`
- Mock `resolve_permitted_groups` to return different group combinations
- Verify error messages and recovery strategies

### Step 2: Enforce admin-only operations in MCP tools
**Location**: `app/tools/` (gofr-iq)

- Update `source_tools.py`: Add `require_admin()` to `create_source`, `update_source`, `delete_source`
- Keep `list_sources` and `get_source` accessible to all authenticated users
- Update tool descriptions to indicate "ADMIN ONLY" where applicable

**Tests** (gofr-iq):
- `test/test_source_tools.py`: Add tests for admin enforcement on create/update/delete
- Test non-admin user gets `PERMISSION_DENIED` error
- Test admin user can perform operations
- Verify list/get remain accessible to non-admin users

**Note**: Group and token management tools will be added later in gofr-common integration

### Step 3: Decouple sources from groups (Model & Storage)
**Location**: `app/models/source.py`, `app/services/source_registry.py` (gofr-iq)

**3a. Update Source Model**:
- Remove `group_guid` field from `Source` model entirely
- Update docstrings to reflect standalone nature
- Remove group-related validation

**3b. Update SourceRegistry Storage**:
- Change `_get_source_path()` to return `self._sources_path / f"{source_guid}.json"` (flat)
- Remove `_get_group_path()` method
- Update `_list_all_groups()` → rename to `_list_all_sources()` (scans flat directory)
- Update `create()`: remove `group_guid` parameter
- Update `get()`: remove `access_groups` parameter and validation
- Update `list_sources()`: remove `group_guid` filtering
- Update `update()` and `soft_delete()`: remove group access checks

**3c. Data Reset (no migration needed)**:
- Since not in production yet, we will **delete all source data** before deploying new version
- Delete `data/storage/sources/` directory completely
- Sources will be recreated with admin token after deployment
- Document this in deployment guide: "Delete data/storage/sources/ before upgrading to v2.x"

**Tests** (gofr-iq):
- `test/test_source_registry.py`: 
  - **Update** all tests to remove `group_guid` parameter from `create()` calls
  - **Remove** `TestSourceAccessControl` class (group-based access no longer exists)
  - **Update** `test_create_source()` to verify flat storage path
  - **Update** `test_list_sources()` to verify no group filtering
  - **Add** `test_create_source_no_group_guid()` to ensure model doesn't have field
- `test/test_models.py`:
  - **Update** source model validation tests to remove group_guid
- Integration tests:
  - `test/test_integration_*.py`: Update any source creation to remove group_guid

### Step 4: Update ingestion validation
**Location**: `app/services/ingest_service.py` (gofr-iq)

- Update `ingest()` method: remove group-based source validation
- Update source existence check: `self.source_registry.get(source_guid)` (no access_groups param)
- Ensure document's `group_guid` comes from caller's token only
- Keep `source_guid` as metadata reference in document

**Tests** (gofr-iq):
- `test/test_ingest_service.py`:
  - **Remove** tests for source-group validation (e.g., `test_ingest_rejects_source_from_different_group`)
  - **Update** `test_ingest_validates_source()` to only check source existence
  - **Add** `test_ingest_accepts_any_source_for_any_group()` to verify cross-group usage
- `test/test_ingest_integration.py`:
  - **Update** integration tests to use sources created without group_guid
  - **Add** test showing public group doc can reference admin-created global source

### Step 5: Update MCP ingest tools
**Location**: `app/tools/ingest_tools.py` (gofr-iq)

- Update `ingest_document` tool: remove source-group validation logic
- Update `validate_document` tool: remove source access_groups parameter
- Update error messages to reflect global source model

**Tests** (gofr-iq):
- `test/test_ingest_tools.py`:
  - **Remove** tests for source-group access denied scenarios
  - **Add** test for any authenticated user ingesting with any source
  - Verify group assignment comes from token, not source

### Step 6: Bootstrap documentation and verification
**Location**: `docs/getting-started/` (gofr-iq)

- Create `bootstrap-guide.md` with step-by-step CLI bootstrap process
- Document Vault root token requirement
- Provide verification steps after admin token generation
- Add troubleshooting section

**Tests** (gofr-iq):
- `test/test_bootstrap.py` (new):
  - Test admin token creation via CLI (integration test)
  - Test admin token can create sources/groups
  - Test non-admin token cannot create sources/groups

### Step 7: Add group/token management tools (gofr-common)
**Location**: `lib/gofr-common/src/gofr_common/auth/` (gofr-common)

- Ensure `GroupRegistry` has proper admin checks if exposed via API
- Verify token creation in `AuthService` includes group validation

**Tests** (gofr-common):
- `lib/gofr-common/test/test_groups.py`:
  - **Add** tests for reserved groups (admin, public) cannot be deleted
  - **Add** tests for group lifecycle
- `lib/gofr-common/test/test_auth_service.py`:
  - **Add** tests for token creation with admin validation
  - Test token with admin group can create other tokens
  - Test token without admin group cannot create tokens

### Step 8: Update all integration tests
**Location**: `test/` (gofr-iq)

**8a. Update MCPO/MCP integration tests**:
- `test/test_mcp_server_integration.py`: Update source creation calls
- `test/test_mcpo_group_access.py`: Update `ensure_source()` to create flat sources
- Remove any source-group access tests

**8b. Update end-to-end tests**:
- `test/test_end_to_end_ingest_query.py`: 
  - Update source fixtures to not include group_guid
  - Verify documents in different groups can reference same source
- `test/test_integration_graph_ranking.py`:
  - Update test data setup for global sources

**8c. Update test fixtures**:
- `test/conftest.py`: Update source fixtures to create flat sources
- `test/fixtures.py`: Remove group_guid from source creation helpers

### Step 9: Update documentation
**Location**: `docs/` (gofr-iq)

- `docs/architecture/authentication.md`: Remove source-group linkage, add admin requirements
- `docs/features/group-access.md`: Update source access section
- `docs/features/document-ingestion.md`: Update source validation section
- `docs/reference/api-reference.md`: Update source tool descriptions
- `readme.md`: Add bootstrap section with admin token creation

### Step 10: Validation and cleanup
**Final checks**:

- Run full test suite in gofr-common: `lib/gofr-common/scripts/run_tests.sh`
- Run full test suite in gofr-iq: `scripts/run_tests.sh`
- Verify no references to source `group_guid` remain in code
- Check all error messages provide recovery guidance
- Run migration script on copy of production data
- Document rollback procedures

**Test coverage targets**:
- gofr-common: Maintain >90% coverage for auth module
- gofr-iq: Maintain >85% coverage overall, 100% for new admin checks

**Note**: Always use the provided test runners (`scripts/run_tests.sh` for gofr-iq and `lib/gofr-common/scripts/run_tests.sh` for gofr-common) rather than calling pytest directly. These scripts ensure proper environment setup and test configuration.
