# Authentication & Access Control

## Overview

GOFR-IQ uses JWT-based authentication with group-scoped access control. Tokens flow transparently through the system until reaching components that enforce permissions.

**Key Principle**: JWT tokens are passed through layers unchanged until they reach the service that needs to enforce access control.

---

## Authentication Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│    Client    │────▶│     MCPO     │────▶│  MCP Server  │────▶│   Services   │
│ (API/Browser)│     │ (REST Proxy) │     │  (FastMCP)   │     │ (Query/Ingest│
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
      │                     │                     │                     │
      │ Authorization:      │  Forwards           │ Validates           │ Enforces
      │ Bearer <JWT>        │  unchanged          │ token               │ groups
      └─────────────────────┴─────────────────────┴─────────────────────┘
                                                   │
                                        Extracts: ["group-a", "public"]
```

---

## Components

### 1. Client Layer
- Sends requests with optional `Authorization: Bearer <JWT>` header
- Token contains group claims: `{"groups": ["group-a", "group-b"]}`
- No token = implicitly treated as `public` group only

### 2. MCPO (REST-to-MCP Proxy)
**Role**: Protocol translator only

- **Does NOT** validate tokens
- **Does NOT** use API keys
- Forwards `Authorization` header unchanged to MCP server
- Converts REST/HTTP requests to MCP protocol

**Correct Configuration**:
```bash
mcpo --host 0.0.0.0 --port 8181 \
     --server-type streamable-http \
     -- "http://localhost:8180/mcp"
```

### 3. MCP Server
**Role**: Token validation and context setup

**When Auth Enabled**:
1. `AuthHeaderMiddleware` extracts JWT from header
2. Stores token in request context (ContextVar)
3. Tools call `get_permitted_groups_from_context()`
4. JWT validated and groups extracted
5. Services receive permitted groups list

**When Auth Disabled** (`--no-auth`):
- All requests implicitly use `["public"]` group
- No token validation occurs
- Useful for development/testing

### 4. Services Layer
**Role**: Group-based filtering

Services (QueryService, IngestService, etc.) receive permitted groups and:
- Filter query results to only return documents in accessible groups
- Enforce write permissions for ingest operations
- Validate source access based on group membership

---

## Token Structure

### JWT Claims

```json
{
  "groups": ["reuters-feed", "bloomberg", "public"],
  "exp": 1735689600,
  "iat": 1704153600,
  "sub": "client-guid-123"
}
```

**Standard Claims**:
- `groups`: Array of group names this token can access
- `exp`: Expiration timestamp (Unix epoch)
- `iat`: Issued at timestamp
- `sub`: Subject (usually client GUID or user ID)

### Group Semantics

- `public`: Reserved group, always accessible even without token
- `admin`: Administrative access (can create/delete sources, manage groups)
- Custom groups: Content-specific (e.g., `reuters-feed`, `alt-data-provider`)

---

## Access Control Model

### Read Access

**Documents**:
- User can read document if token includes any of the document's groups
- Example: Document in `["reuters-feed"]` accessible to tokens with `reuters-feed` OR `admin`

**Sources**:
- User can list/view source if token includes source's group
- Public sources visible to all

### Write Access

**Document Ingestion**:
- Requires valid token with write permission to target group
- Document stored in group matching token's primary group (first in array)

**Source Management**:
- Create/Update/Delete requires `admin` group membership
- Sources inherit group from creating token

---

## Bootstrap Tokens

On system initialization, two special tokens are created:

### Public Token
```bash
export GOFR_IQ_PUBLIC_TOKEN="eyJ..."
```
- Groups: `["public"]`
- Purpose: Default/anonymous access
- Expiry: Never (100 years)
- Used by: Web UI, public API clients

### Admin Token
```bash
export GOFR_IQ_ADMIN_TOKEN="eyJ..."
```
- Groups: `["admin"]`
- Purpose: Administrative operations
- Expiry: Never (100 years)
- Used by: Management scripts, CI/CD, setup tools

**Bootstrap Script**:
```bash
python scripts/bootstrap_auth.py
```

---

## Authentication Backends

GOFR-IQ supports three auth backends via `gofr-common`:

### 1. Vault (Production)
```bash
export GOFR_AUTH_BACKEND=vault
export GOFR_VAULT_URL=http://localhost:8200
export GOFR_VAULT_TOKEN=root-token
```
- Centralized token storage
- Multi-service coordination
- Token revocation support
- Audit logging

### 2. File (Development)
```bash
export GOFR_AUTH_BACKEND=file
export GOFR_IQ_TOKEN_STORE=data/auth/tokens.json
export GOFR_IQ_GROUP_STORE=data/auth/groups.json
```
- JSON file storage
- Simple, local-first
- No external dependencies

### 3. Memory (Testing)
```bash
export GOFR_AUTH_BACKEND=memory
```
- In-memory storage only
- Ephemeral (lost on restart)
- Fast, isolated tests

---

## Permission Matrix

| Operation | Public Token | Group Token | Admin Token |
|-----------|--------------|-------------|-------------|
| Read public docs | ✅ | ✅ | ✅ |
| Read group docs | ❌ | ✅ (if in group) | ✅ |
| Ingest to public | ❌ | ❌ | ✅ |
| Ingest to group | ❌ | ✅ (if in group) | ✅ |
| Create source | ❌ | ❌ | ✅ |
| List sources | ✅ (public only) | ✅ (permitted) | ✅ (all) |
| Query documents | ✅ (public only) | ✅ (permitted) | ✅ (all) |
| Get client feed | ❌ | ✅ (own client) | ✅ (any client) |

---

## Usage Examples

### Creating a Group Token

```bash
# Using create_group.py script
python scripts/create_group.py reuters-feed --expires 2592000

# Output
GOFR_IQ_REUTERS_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Using Tokens in Requests

**Via MCPO (REST)**:
```bash
curl -X POST http://localhost:8181/query_documents \
  -H "Authorization: Bearer ${GOFR_IQ_REUTERS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"query_text": "semiconductor shortage", "k": 10}'
```

**Via MCP Client**:
```python
from mcp import Client

client = Client(
    url="http://localhost:8180/mcp",
    headers={"Authorization": f"Bearer {token}"}
)

results = await client.call_tool("query_documents", {
    "query_text": "semiconductor shortage",
    "k": 10
})
```

### Programmatic Token Validation

```python
from gofr_common.auth import AuthService

auth = AuthService(
    jwt_secret=os.getenv("GOFR_IQ_JWT_SECRET"),
    token_store=token_store,
    groups=group_registry
)

# Validate token
token_info = auth.verify_token(jwt_token)
if token_info:
    print(f"Valid! Groups: {token_info.groups}")
else:
    print("Invalid or expired token")
```

---

## Security Considerations

### Token Management
- **Rotation**: Tokens should expire and be rotated periodically
- **Storage**: Never commit tokens to version control
- **Transmission**: Always use HTTPS in production
- **Revocation**: Use Vault backend for immediate revocation

### JWT Security
- **Secret Key**: Use strong, random `GOFR_IQ_JWT_SECRET` (min 32 chars)
- **Algorithm**: HS256 (HMAC with SHA-256)
- **Expiry**: Set reasonable exp times (30-90 days for user tokens)
- **Claims**: Validate all standard claims (exp, iat, nbf)

### Group Isolation
- Groups provide content boundaries, not security boundaries
- Assume users can see all content in their permitted groups
- Never rely on groups alone for sensitive data separation

---

## Troubleshooting

### "Invalid token" errors
```bash
# Check token expiry
python -c "import jwt; print(jwt.decode('${TOKEN}', verify=False))"

# Verify JWT secret matches
echo $GOFR_IQ_JWT_SECRET

# Check token in store
python scripts/token_manager.sh list
```

### "Access denied" errors
```bash
# Verify token groups
python scripts/token_manager.sh inspect ${TOKEN}

# Check document groups
# Documents must be in one of token's groups
```

### MCPO not forwarding tokens
```bash
# Verify MCPO startup (no --api-key)
ps aux | grep mcpo

# Check Authorization header in MCP logs
tail -f logs/mcp_server.log | grep Authorization
```

---

## Related Documentation

- [Group Access Control](../features/group-access.md) - Detailed permission model
- [Configuration Guide](../getting-started/configuration.md) - Auth environment variables
- [Testing Auth](../development/testing.md#authentication-tests) - Auth test patterns
