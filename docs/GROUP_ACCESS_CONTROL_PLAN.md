# GoFr-IQ Group Access Control Implementation Plan

> Created: December 14, 2025
> Status: Planning
> Reference: gofr-plot group implementation model

## Current State Analysis

| Component | Current State | Target State |
|-----------|---------------|--------------|
| Group source | Client passes `group_guid` | Extract from JWT token |
| Default group | None (required param) | `"public"` for unauthenticated |
| Enforcement | Trust caller | Strict server-side |
| Graph access | No filtering | Filter by permitted groups |
| Document access | Directory-based | Directory + query filtering |

---

## Phase 1: Group Service (Align with Plot)

### 1.1 Create `GroupService` (new file: `app/services/group_service.py`)

```python
class GroupService:
    def extract_group_from_request(self, token: str | None) -> str:
        """Extract group from JWT token or return public."""
        # If token: extract group from JWT
        # If no token: return "public"
    
    def get_permitted_groups(self, token: str | None) -> list[str]:
        """Get all groups user can access."""
        # Returns ["public"] + token's groups
    
    def validate_group_access(self, token: str | None, group_guid: str) -> bool:
        """Check if user can access requested group."""
        # Check if user can access requested group
```

### 1.2 Update MCP Server
- Inject `GroupService` into MCP server
- Extract group at request level (not tool level)
- Pass `permitted_groups` to all tools automatically

---

## Phase 2: Tool Parameter Changes

### Remove `group_guid` as client parameter for read operations:

```python
# BEFORE: Client specifies group (unsafe)
def query_documents(query: str, group_guids: list[str], ...)

# AFTER: Server extracts from token (safe)
def query_documents(query: str, ...)  # group_guids injected by server
```

### Keep `group_guid` for write operations but validate:

```python
# Write to specific group - validate token has write access
def ingest_document(title, content, source_guid, group_guid):
    # Server validates: token.group == group_guid OR token has cross-group write
```

---

## Phase 3: Storage Layer Enforcement

### 3.1 DocumentStore - Add group filtering

```python
def load(self, guid: str, permitted_groups: list[str]) -> Document:
    doc = self._load_raw(guid)
    if doc.group_guid not in permitted_groups:
        raise AccessDeniedError(...)
    return doc

def list_documents(self, permitted_groups: list[str], ...) -> list[Document]:
    # Only return docs in permitted groups
```

### 3.2 SourceRegistry - Same pattern

```python
def get(self, source_guid: str, permitted_groups: list[str]) -> Source:
    source = self._load_raw(source_guid)
    if source.group_guid not in permitted_groups:
        raise AccessDeniedError(...)
```

---

## Phase 4: Graph Layer Enforcement (Critical)

### 4.1 Add Group Node and Relationships

```cypher
(:Group {guid: "...", name: "APAC Research"})
(:Document)-[:IN_GROUP]->(:Group)
(:Source)-[:IN_GROUP]->(:Group)
(:Client)-[:HAS_ACCESS_TO]->(:Group)
```

### 4.2 Inject Group Filter in ALL Queries

```python
class GraphIndex:
    def query_with_groups(self, query: str, permitted_groups: list[str]):
        # Every Cypher query MUST include:
        # WHERE (d)-[:IN_GROUP]->(g:Group) AND g.guid IN $permitted_groups
```

### 4.3 Graph Query Wrapper

```python
def _enforce_group_access(self, cypher: str, permitted_groups: list[str]) -> str:
    """Inject group filtering into any Cypher query."""
    # Wrap query to filter by permitted groups
    # This is the STRICT ENFORCEMENT layer
```

---

## Phase 5: Query Service Integration

### 5.1 Hybrid Query (embedding + graph)

```python
def query(self, query_text: str, permitted_groups: list[str], ...):
    # 1. ChromaDB search - filter by group in metadata
    # 2. Graph enrichment - filter by group relationships
    # 3. Return only accessible documents
```

### 5.2 ChromaDB Metadata Filter

```python
# Add group to embedding metadata
collection.add(
    documents=[content],
    metadatas=[{"group_guid": group_guid, ...}],
)

# Query with group filter
collection.query(
    query_texts=[query],
    where={"group_guid": {"$in": permitted_groups}},
)
```

---

## Phase 6: Public Group Handling

### 6.1 Public Group Definition

```python
PUBLIC_GROUP_GUID = "00000000-0000-0000-0000-000000000000"
PUBLIC_GROUP_NAME = "public"
```

### 6.2 Public Access Rules

- Unauthenticated users: `permitted_groups = [PUBLIC_GROUP_GUID]`
- Authenticated users: `permitted_groups = [PUBLIC_GROUP_GUID, token.group, ...]`
- Public content readable by all, writable by admins only

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `app/services/group_service.py` | **CREATE** | Central group management |
| `app/tools/*.py` | MODIFY | Remove client group params, use injected |
| `app/services/document_store.py` | MODIFY | Add group filtering |
| `app/services/source_registry.py` | MODIFY | Add group filtering |
| `app/services/graph_index.py` | MODIFY | Add group filtering to all queries |
| `app/services/query_service.py` | MODIFY | Integrate group filtering |
| `app/services/embedding_index.py` | MODIFY | Add group to metadata + filtering |
| `app/mcp_server/mcp_server.py` | MODIFY | Extract group from token |
| `app/models/group.py` | MODIFY | Add PUBLIC_GROUP constant |

---

## Implementation Order

1. **Phase 1**: GroupService + MCP integration
2. **Phase 6**: Public group constants
3. **Phase 3**: Storage layer enforcement
4. **Phase 5.2**: ChromaDB group filtering
5. **Phase 4**: Graph layer enforcement
6. **Phase 2**: Tool parameter cleanup
7. **Phase 5.1**: Query service integration

---

## Design Decisions (Confirmed Dec 14, 2025)

| Question | Decision |
|----------|----------|
| **Cross-group access** | One token = one group (strict 1:1). Users needing multiple groups get multiple tokens. |
| **Admin override** | No admin bypass. All access goes through group filtering. |
| **Migration** | Existing test data in `550e8400-...` will be migrated to `public` group. |
| **Graph relationships** | Group nodes are first-class citizens with `IN_GROUP` relationships. |

---

## Testing Strategy

1. Unit tests for GroupService
2. Integration tests for each storage layer
3. End-to-end tests: unauthenticated → public only
4. End-to-end tests: authenticated → public + own group
5. Negative tests: access denied for other groups
6. Graph traversal tests: ensure no cross-group leakage
