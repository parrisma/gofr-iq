# Group Access Control

GOFR-IQ implements **group-based access control** to securely isolate data between organizations while enabling cross-group search within permitted groups.

---

## Access Control Model

### Core Concept: Groups

A **group** is the fundamental unit of **permission boundary**:

```
┌─────────────────────────────────────┐
│         GROUP (apac-research)       │
├─────────────────────────────────────┤
│ All Documents, Sources, Clients     │
│ must belong to exactly one group    │
│                                     │
│ ├─ Documents (1000+)               │
│ ├─ Sources (5+)                    │
│ └─ Clients (10+)                   │
└─────────────────────────────────────┘
```

### User-to-Group Mapping

Users get **JWT tokens** with group membership:

```python
{
  "sub": "user-1234",
  "preferred_username": "john.smith",
  "groups": ["apac-research", "japan-desk", "trading"],
  "scopes": ["read", "write"],
  "iat": 1735939200,
  "exp": 1735939200 + 86400
}
```

| Field | Purpose | Example |
|-------|---------|---------|
| `sub` | User ID | `user-1234` |
| `groups` | Group membership (can have 1+) | `["apac-research", "japan-desk"]` |
| `scopes` | Permission level | `["read", "write", "admin"]` |
| `iat` | Issued at (timestamp) | `1735939200` |
| `exp` | Expires (timestamp) | `1735939200 + 86400` |

---

## Scope Levels

Each user has **scopes** controlling what they can do:

| Scope | Permissions | Typical User |
|-------|------------|--------------|
| **read** | Query documents, view feeds | Analyst, trader |
| **write** | Ingest documents, update sources | Data engineer, editor |
| **admin** | Manage groups, create tokens, audit logs | Admin, manager |

### Permission Matrix

| Operation | read | write | admin |
|-----------|------|-------|-------|
| Query documents | ✅ | ✅ | ✅ |
| View client feeds | ✅ | ✅ | ✅ |
| Ingest documents | ❌ | ✅ | ✅ |
| Create sources | ❌ | ✅ | ✅ |
| Update sources | ❌ | ✅ | ✅ |
| Create tokens | ❌ | ❌ | ✅ |
| View audit logs | ❌ | ❌ | ✅ |
| Manage groups | ❌ | ❌ | ✅ |

---

## Database Schema: IN_GROUP Relationship

Every permissioned node must have `IN_GROUP` relationship:

```cypher
// Documents MUST belong to exactly one group
(Document)-[:IN_GROUP]->(Group)

// Sources MUST belong to exactly one group
(Source)-[:IN_GROUP]->(Group)

// Clients MUST belong to exactly one group
(Client)-[:IN_GROUP]->(Group)

// But NOT these - they're global reference data:
Instrument  # Shared across all groups
Index       # Shared taxonomy
Sector      # Shared taxonomy
Company     # Shared taxonomy
EventType   # Shared taxonomy
```

---

## Access Enforcement

### Rule 1: Query Filter

**Every query returning permissioned content must include group filter**:

```cypher
// CORRECT: Filter by group
MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN $permitted_groups
RETURN d

// WRONG: Missing group filter - NEVER
MATCH (d:Document)
RETURN d
```

### Rule 2: Cross-Group Queries

User can query **across multiple permitted groups** simultaneously:

```cypher
// User with groups: ["apac-research", "japan-desk", "trading"]
// Can search across all three:

MATCH (d:Document)-[:IN_GROUP]->(g:Group)
WHERE g.group_guid IN ["apac-research", "japan-desk", "trading"]
RETURN d
```

### Rule 3: Source Validation

When ingesting documents, validate source belongs to user's group:

```python
def ingest(title: str, content: str, source_guid: str, user_groups: list[str]):
    # Verify source is in one of user's permitted groups
    source = source_registry.get(source_guid)
    
    if source.group_guid not in user_groups:
        raise PermissionError(
            f"Source {source_guid} not in your groups: {user_groups}"
        )
    
    # Ingest with source's group
    return ingest_service.ingest(
        title=title,
        content=content,
        source_guid=source_guid,
        group_guid=source.group_guid  # Use source's group
    )
```

---

## Implementation in FastAPI

### Dependency: Current User with Groups

```python
from fastapi import Depends, HTTPException
from app.auth import get_current_user

async def get_current_user_with_groups(token: str = Depends(oauth2_scheme)):
    """Verify JWT token and extract groups."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        groups = payload.get("groups", [])
        if not groups:
            raise HTTPException(401, "No groups in token")
        return {"sub": payload["sub"], "groups": groups}
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
```

### Endpoint: Search Documents

```python
@app.get("/api/v1/search")
async def search(
    query: str,
    user: dict = Depends(get_current_user_with_groups)
):
    """Search documents across user's permitted groups."""
    
    results = query_service.search(
        query=query,
        permitted_groups=user["groups"],  # Pass user's groups
        limit=10
    )
    
    return {"results": results}
```

### Endpoint: Ingest Document

```python
@app.post("/api/v1/ingest")
async def ingest(
    doc: DocumentCreate,
    user: dict = Depends(get_current_user_with_groups)
):
    """Ingest document into user's permitted group."""
    
    # Verify source is in user's groups
    source = source_registry.get(doc.source_guid)
    if source.group_guid not in user["groups"]:
        raise HTTPException(403, "Source not in your groups")
    
    # Ingest with source's group
    result = ingest_service.ingest(
        title=doc.title,
        content=doc.content,
        source_guid=doc.source_guid,
        group_guid=source.group_guid,  # Use source's group
        language=doc.language,
        metadata=doc.metadata
    )
    
    return result.to_dict()
```

---

## Token Management

### Creating Tokens

**Admin only** - requires `admin` scope:

```python
from datetime import datetime, timedelta, timezone
import jwt

@app.post("/api/v1/tokens")
async def create_token(
    username: str,
    groups: list[str],
    scopes: list[str],
    expiry_days: int = 30,
    user: dict = Depends(get_current_user_with_groups)
):
    """Create JWT token for user (admin only)."""
    
    # Verify caller has admin scope
    if "admin" not in user.get("scopes", []):
        raise HTTPException(403, "Admin scope required")
    
    # Create token payload
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "preferred_username": username,
        "groups": groups,
        "scopes": scopes,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=expiry_days)).timestamp())
    }
    
    # Sign token
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    
    # Store in token service for revocation
    token_service.store(token, payload)
    
    return {"token": token}
```

### Token Revocation

**Admin only** - can revoke tokens:

```python
@app.post("/api/v1/tokens/revoke")
async def revoke_token(
    token: str,
    user: dict = Depends(get_current_user_with_groups)
):
    """Revoke a token (admin only)."""
    
    if "admin" not in user.get("scopes", []):
        raise HTTPException(403, "Admin scope required")
    
    token_service.revoke(token)
    
    return {"message": "Token revoked"}
```

---

## Multi-Tenancy Example

### Scenario: Three Organizations

```
Organization A (apac-research)
├─ Group: "apac-research"
├─ Users: alice@org-a.com, bob@org-a.com
├─ Documents: 5000+
├─ Sources: Reuters, Bloomberg
└─ Clients: Fund A, Fund B

Organization B (japan-desk)
├─ Group: "japan-desk"
├─ Users: yamada@org-b.com, tanaka@org-b.com
├─ Documents: 3000+
├─ Sources: Nikkei, Mainichi
└─ Clients: Fund C

Organization C (trading)
├─ Group: "trading"
├─ Users: charlie@org-c.com, diana@org-c.com
├─ Documents: 2000+
├─ Sources: Reuters, Bloomberg
└─ Clients: Fund D
```

### Cross-Organization User

Executive with access to all:

```
User: exec@parent-org.com
Token: {
  "groups": ["apac-research", "japan-desk", "trading"],
  "scopes": ["read", "admin"]
}

Permissions:
- Search across all 3 groups
- View documents from all 3 groups
- Manage all 3 groups
- Cannot ingest (no write scope)
```

---

## Group Management

### Creating Groups

```python
@app.post("/api/v1/groups")
async def create_group(
    name: str,
    user: dict = Depends(get_current_user_with_groups)
):
    """Create a new group (admin only)."""
    
    if "admin" not in user.get("scopes", []):
        raise HTTPException(403, "Admin scope required")
    
    group = graph_index.create_group(
        guid=str(uuid.uuid4()),
        name=name
    )
    
    return {"group_guid": group.guid, "name": group.name}
```

### Adding Members to Group

```python
@app.post("/api/v1/groups/{group_id}/members")
async def add_group_member(
    group_id: str,
    username: str,
    scopes: list[str],
    user: dict = Depends(get_current_user_with_groups)
):
    """Add user to group (admin only)."""
    
    if "admin" not in user.get("scopes", []):
        raise HTTPException(403, "Admin scope required")
    
    # Update user's token to include new group
    # (typically done via auth backend)
    token_service.add_group(username, group_id, scopes)
    
    return {"message": f"{username} added to {group_id}"}
```

---

## Audit & Security

### Audit Logging

Every operation logged with user identity:

```python
def log_operation(
    operation: str,
    user: str,
    groups: list[str],
    resource: str,
    status: str
):
    """Log all access for audit."""
    audit_service.log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "user": user,
        "groups": groups,
        "resource": resource,
        "status": status  # "success" or "denied"
    })

# Example logs:
# {"operation": "search", "user": "alice", "groups": ["apac-research"], "resource": "documents", "status": "success"}
# {"operation": "ingest", "user": "bob", "groups": ["japan-desk"], "resource": "source-xyz", "status": "denied"}
```

### Group Breach Scenarios

| Scenario | Protection |
|----------|-----------|
| User queries unauthorized group | IN_GROUP filter blocks (at DB level) |
| User ingestsinto unauthorized group | Source validation checks (at API level) |
| Malicious user modifies token | JWT signature verified (at auth level) |
| Token leaked | Revocation + expiration (24 hours) |
| Deleted user still has token | Token service blacklist + rotation |

---

## Best Practices

### 1. Always Validate Groups

```python
# ALWAYS verify on every API call
@app.get("/api/v1/documents/{doc_id}")
async def get_document(
    doc_id: str,
    user: dict = Depends(get_current_user_with_groups)
):
    doc = document_store.get(doc_id)
    
    # Verify document is in user's groups
    if doc.group_guid not in user["groups"]:
        raise HTTPException(403, "Document not in your groups")
    
    return doc
```

### 2. Fail Closed

```python
# If group check fails, deny access (fail closed)
if document.group_guid not in user.groups:
    raise PermissionError()  # Always deny, never allow
```

### 3. Rotate Tokens

```bash
# Tokens expire after 24 hours (configurable)
export GOFR_IQ_JWT_EXPIRATION=86400  # 1 day

# Users must re-authenticate for new token
# Limits damage if token is leaked
```

### 4. Audit Everything

```python
# Every operation logged
audit_service.log({
    "operation": operation_name,
    "user": user_id,
    "groups": user_groups,
    "resource": resource_id,
    "status": result_status,
    "timestamp": now
})

# Review daily
audit_service.generate_daily_report()
```

---

## Related Documentation

- [Authentication Architecture](../architecture/authentication.md)
- [Configuration Reference](../getting-started/configuration.md)
- [Architecture Overview](../architecture/overview.md)
