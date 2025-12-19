# Authentication Architecture

## Overview

This document describes how authentication flows through the gofr-iq system.

**Key Principle:** JWT tokens flow through the system untouched until they reach the component that needs to enforce access control.

---

## Auth Flow Summary

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     Client      │───▶│      MCPO      │────▶ │   MCP Server    │
│  (curl/browser) │     │  (REST Wrapper) │     │   (FastMCP)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │ Filters results
        ▼                       ▼                       ▼
   Optional JWT            Forwards header          Group-based
   for group access        unchanged to MCP         access control
```

---

## 1. MCPO (REST Wrapper for MCP)

**Role:** Transparent pass-through proxy that converts REST calls to MCP protocol.

### Behavior

| Scenario | MCPO Action | Result |
|----------|-------------|--------|
| Client sends `Authorization: Bearer <JWT>` | Forwards header to MCP unchanged | MCP validates and applies group access |
| Client sends no token | Forwards request without auth header | MCP allows only `public` group access |

### Key Points

- **MCPO does NOT validate JWT tokens** - it's just a protocol translator
- **MCPO does NOT use `--api-key`** - no MCPO-level authentication
- **MCPO forwards Authorization header** - MCP receives the JWT as-is

### Configuration

```bash
# Correct MCPO startup (no --api-key)
mcpo --host 0.0.0.0 --port 8081 \
     --server-type streamable-http \
     -- "http://localhost:8080/mcp"
```

---

## 2. MCP Server (Auth Mode)

**Role:** Validates JWT tokens and enforces group-based access control on all queries.

### Behavior

When started in **Auth Mode**, MCP Server:

1. **Extracts JWT** from `Authorization: Bearer <token>` header
2. **Validates token** signature, expiry, and group claims
3. **Resolves groups** from `token_info.groups` (list of group names)
4. **Filters all responses** to only include data accessible to those groups

### Auth Flow in MCP

```
Request arrives
       │
       ▼

 AuthHeaderMiddleware     │
 stores header in         │
 ContextVar               │

             │
             ▼

 MCP Tool executes        │
 calls get_permitted_     │
 groups_from_context()    │

             │
             ▼

 JWT validated            │
 groups extracted         │
 ["group-a", "public"]    │

             │
             ▼

 Query results filtered   │
 Only docs in permitted   │
 groups returned          │

```

### No Token = Public Access Only

If no JWT is provided:
- `get_permitted_groups_from_context()` returns `["public"]`
- Only documents/data in the `public` group are accessible
- No error is raised (anonymous access is allowed)

---

## 3. Web Server (Auth Mode)

**Role:** REST API that delegates to MCP for actual operations.

### Behavior

When started in **Auth Mode**, Web Server:

1. **Requires JWT** in `Authorization: Bearer <token>` header
2. **Validates token** for endpoint access (FastAPI dependency)
3. **Passes token to MCP** when making internal MCP calls
4. **MCP enforces group access** on the underlying queries

### Auth Flow in Web Server

```
Client Request
       │
       ▼

 FastAPI Dependency       │
 verify_token()           │
 validates JWT            │

             │
             ▼

 Endpoint handler         │
 receives TokenInfo       │
 with groups              │

             │
             ▼

 Internal MCP call        │
 passes JWT header        │
 for group filtering      │

```

---

## gofr-common AuthService v2

The `gofr_common.auth.AuthService` provides JWT token management.

### Features

- **Multi-group tokens**: Tokens can grant access to multiple groups
- **Group registry**: Groups must exist before token creation
- **Reserved groups**: `public` and `admin` are auto-bootstrapped
- **Group helpers**: `has_group()`, `has_any_group()`, `has_all_groups()`

### Token Structure

```json
{
  "groups": ["group-a", "group-b"],  // Multi-group support
  "iat": 1734271200,                 // Issued at
  "exp": 1736863200,                 // Expires at
  "aud": "gofr_iq-api"               // Audience
}
```

### Usage Example

```python
from gofr_common.auth import AuthService, TokenInfo

# Initialize (auto-bootstraps reserved groups: public, admin)
auth = AuthService(
    secret_key="my-secret",
    token_store_path="/path/to/tokens.json",
)

# Create custom groups
auth.groups.create_group("customers", "Customer users")
auth.groups.create_group("premium", "Premium subscribers")

# Create multi-group token
token = auth.create_token(groups=["customers", "premium"])

# Verify and check groups
token_info = auth.verify_token(token)
print(token_info.groups)           # ["customers", "premium"]
print(token_info.has_group("premium"))  # True
```

### FastAPI Integration

```python
from gofr_common.auth import verify_token, require_admin, require_group

@app.get("/documents")
def list_documents(token_info: TokenInfo = Depends(verify_token)):
    # token_info.groups contains user's groups
    return {"groups": token_info.groups}

@app.post("/admin/groups")
def create_group(token_info: TokenInfo = Depends(require_admin)):
    # Only admin users can access
    pass

@app.get("/premium/content")
def premium_content(token_info: TokenInfo = Depends(require_group("premium"))):
    # Only users with "premium" group can access
    pass
```

---

## Group Access Control

### How Groups Work

| Group | Description | Access |
|-------|-------------|--------|
| `public` | Reserved, auto-created | Everyone (even anonymous) |
| `admin` | Reserved, auto-created | Full system access |
| Custom groups | Created via registry | Token must include group |

### Access Rules

1. **Read Access**: Token's groups + `public` group
2. **Write Access**: Only token's explicit groups (not public)
3. **Anonymous**: Only `public` group (no write access)

### Example: Document Filtering

```python
# User has token with groups=["customers"]
permitted = get_permitted_groups(token_info)  # ["customers", "public"]

# Query returns only documents where:
#   document.group_guid IN ["customers", "public"]
```

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GOFR_IQ_JWT_SECRET` | Secret key for signing/verifying JWTs |
| `GOFR_IQ_TOKEN_STORE` | Path to token store JSON file |
| `GOFR_IQ_MCP_PORT` | MCP server port (default: 8080) |
| `GOFR_IQ_MCPO_PORT` | MCPO proxy port (default: 8081) |
| `GOFR_IQ_WEB_PORT` | Web server port (default: 8000) |

---

## Key Files

| File | Purpose |
|------|---------|
| `lib/gofr-common/.../auth/service.py` | AuthService - JWT creation/verification |
| `lib/gofr-common/.../auth/groups.py` | GroupRegistry, RESERVED_GROUPS |
| `lib/gofr-common/.../auth/middleware.py` | FastAPI dependencies (verify_token, etc.) |
| `lib/gofr-common/.../web/middleware.py` | AuthHeaderMiddleware for ContextVar |
| `app/auth/__init__.py` | Re-exports gofr_common.auth v2 API |
| `app/services/group_service.py` | get_permitted_groups_from_context() |
| `app/auth/group_access.py` | Document-level group access control |

---

## Complete Auth Flow Diagram

```
                    ┌─────────────────┐                    ┌──────
     Client      │                    │      MCPO       │                    │   MCP Server    │
                    └────────┬─                    
         │                                      │                                      │
         │ 1. POST /query_documents             │                                      │
         │    Authorization: Bearer <JWT>       │                                      │
                                      │         │──────────────
         │                                      │                                      │
         │                                      │ 2. Forward to MCP                    │
         │                                      │    (header passed through)           │
         │                                      │───────────────────
         │                                      │                                      │
         │                                      │                      ┌───────────────┴──
         │                                      │                      │ 3. Validate JWT               │
         │                                      │                      │    Extract groups:            │
         │                                      │                      │    ["customers", "premium"]   │
         │                                      │                      └───────────────┬───────────────┘
         │                                      │                                      │
         │                                      │                      ┌────
 4. Permitted groups:          │         │                                      │                      
         │                                      │                      │    ["customers", "premium",   │
         │                                      │                      │     "public"]                 │
         │                                      │                      └───────────────┬───────────────┘
         │                                      │                                      │
         │                                      │                      ┌───────────────┴───────────────┐
         │                                      │                      │ 5. Query filtered by groups   │
         │                                      │                      │    Only matching docs         │
         │                                      │                      │    returned                   │
         │                                      │                      └───────────────┬────
         │                                      │                                      
         │                                      
                                      │         
         │         6. Filtered results          │                                      │
```

---

## Test Token Generation

```python
# Create AuthService with in-memory store (test isolation)
auth = AuthService(secret_key="test-secret", token_store_path=":memory:")

# Pre-create test groups (required by v2)
auth.groups.create_group("group-a", "Test Group A")
auth.groups.create_group("group-b", "Test Group B")

# Create tokens
token_single = auth.create_token(groups=["group-a"])
token_multi = auth.create_token(groups=["group-a", "group-b"])
token_public = auth.create_token(groups=["public"])  # Reserved, always exists
```
