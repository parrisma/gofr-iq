# Implementation Plan: Document Lifecycle & Soft Deletes

**Status**: Draft
**Target Date**: 2026-02-01
**Context**: GOFR-IQ requires robust handling of document retractions, corrections, and client deactivation without losing audit history.

## 1. Overview

This plan details the implementation of "Defunct" (soft-delete) and "Update" (supersede) patterns for Documents and Clients.

### Core Principles
1.  **Immutability**: Documents are never modified in place. An update is a new document that supersedes the old one.
2.  **Audit Trail**: No data is permanently deleted (except via specific GDPR hard-delete tools). "Deleted" items are marked `defunct`.
3.  **Default Filtering**: All standard read queries (`query_documents`, `get_client_feed`) must implicitly exclude defunct items unless specifically requested.

---

## 2. Schema Changes

### 2.1 Document Model
Add fields to the `Document` dataclass and storage backends:
- `defunct` (bool): Default `False`.
- `defunct_at` (datetime): Timestamp when marked defunct.
- `defunct_reason` (str): Enum-like string (e.g., "retracted", "superseded", "error", "gdpr").
- `superseded_by` (str): UUID of the new document replacing this one.
- `supersedes` (str): UUID of the old document this one replaces (on the new doc).
- `version` (int): Incremented version number (v1 -> v2).

### 2.2 Client Model
Add properties to the Client node in Neo4j:
- `defunct` (bool): Default `False`.
- `defunct_at` (datetime).
- `defunct_reason` (str).

### 2.3 Neo4j Indices
Create new indices to ensure filtering by `defunct` status is performant.
- Index on `:Document(defunct)`
- Index on `:Client(defunct)`

---

## 3. Step-by-Step Implementation Plan

### Phase 1: Data Model & Storage Layer (Est. 3 hrs)

#### Step 1.1: Update Document Domain Model
- Modify `app/models/document.py`.
- Add `defunct`, `defunct_at`, `defunct_reason`, `superseded_by`, `supersedes`, `version` fields.
- Update `to_dict()` and `from_dict()` serialization methods.

#### Step 1.2: Update File Storage (DocumentStore)
- Modify `app/services/document_store.py`.
- Ensure new fields are persisted to the JSON file on disk during `save()`.
- Ensure `load()` correctly reads these fields.

#### Step 1.3: Update Graph Index (Neo4j)
- Create a migration script `scripts/migrations/001_add_defunct_indices.cypher`.
- Modify `app/services/graph_index.py`:
    - Update `add_document_node` to write new properties.
    - Update `create_client` to write default `defunct=False`.
    - Add `mark_node_defunct(label, guid, reason)` method.

#### Step 1.4: Update Embedding Index (ChromaDB)
- Modify `app/services/embedding_index.py`.
- Update `add_document` to include `"defunct": False` in chunk metadata.
- Add `mark_document_defunct(guid)` method to update metadata for all chunks of a document.

---

### Phase 2: Read Layer Enforcement (Est. 4 hrs)

*Goal: Ensure no defunct data leaks into standard queries.*

#### Step 2.1: Filter Graph Queries
- Modify `app/services/graph_index.py` query methods.
- Update `get_instrument_news`: Add `WHERE d.defunct = false` to Cypher.
- Update `get_market_context`: Filter defunct news/events.
- Update `get_client_feed`: Add `WHERE d.defunct = false`.

#### Step 2.2: Filter Retrieval Queries (ChromaDB)
- Modify `app/services/query_service.py`.
- In `query()` method, add strict filter to ChromaDB call: `where={"defunct": False}`.
- Ensure this filter is ANDed with existing filters (dates, sources).

#### Step 2.3: Filter Source/SQL Queries (if applicable)
- Verify `SourceRegistry` does not need defunct flags (Sources have specific `active` flag already).

#### Step 2.4: Update Getters
- Update `get_document(guid)` in `app/tools/query_tools.py`.
    - Check `doc.defunct`.
    - If `True`, raise distinct error `DocumentDefunctError` (or return with specific warning flag if requested).
- Update `get_client_profile(guid)` in `app/tools/client_tools.py`.
    - Return specific status if client is defunct.

---

### Phase 3: "Defunct" Tools (Est. 4 hrs)

#### Step 3.1: Implement `defunct_document` Tool
- Locations: `app/tools/ingest_tools.py`
- Logic:
    1. Check permissions (Write access to group).
    2. Call `document_store.update_metadata(defunct=True...)`.
    3. Call `graph_index.mark_node_defunct(...)`.
    4. Call `embedding_index.mark_document_defunct(...)`.
    5. Log audit event.

#### Step 3.2: Implement `defunct_client` Tool
- Locations: `app/tools/client_tools.py`
- Logic:
    1. Check permissions (Admin or owner).
    2. Call `graph_index.mark_node_defunct(CLIENT, ...)`.
    3. Log audit event.

#### Step 3.3: Implement Restore Tools (Admin Only)
- `restore_document` and `restore_client`.
- Reverses flags set in 3.1/3.2.
- Essential for undoing accidental deletions.

---

### Phase 4: "Update" Workflow (Est. 6 hrs)

*Goal: The supersede pattern.*

#### Step 4.1: Extend Ingest Service
- Modify `app/services/ingest_service.py`.
- Add `update_document(old_guid, new_content, ...)` method.
- **Transaction Logic**:
    1. Retrieve old document (Lock/Verify).
    2. Prepare new document object (Version = Old.Version + 1).
    3. Set `supersedes` on New; `superseded_by` on Old.
    4. Ingest New Document (File, Graph, Vector).
    5. Mark Old Document `defunct` (File, Graph, Vector).
    6. **Graph Relationship Migration**:
        - Query all manual relationships from Old (e.g., user-tagged entities).
        - Copy them to New defined as `AFFECTS`, `MENTIONS` etc.

#### Step 4.2: Implement `update_document` Tool
- Locations: `app/tools/ingest_tools.py`.
- Expose the service logic via MCP.
- Parameters: `document_guid`, optional `title`, optional `content`, `reason`.

---

### Phase 5: Verification & Cleanup (Est. 3 hrs)

#### Step 5.1: Unit Tests
- Test Schema serialization.
- Test Filter logic (create defunct doc, ensure it doesn't appear in search).

#### Step 5.2: Integration Tests
- Run `test_end_to_end_ingest_query.py`.
- Add specific test case: `test_document_lifecycle_update_supersede`.

#### Step 5.3: Documentation
- Update `docs/features/document-ingestion.md` with new Lifecycle section.
- Update `app/tools/ingest_tools.py` docstrings.

---

## 4. Dependencies & Risks

- **Risk**: "Ghost" embeddings. If ChromaDB metadata update fails, defunct docs might still appear in vector search.
    - *Mitigation*: Implementation must verify Chroma update acknowledgment.
- **Risk**: External references. Users might store GUIDs that become defunct.
    - *Mitigation*: `get_document` should return specific "Superseded by X" message instead of generic 404.

## 5. Security Implications

- **Auth**: Only users with WRITE access to the group can defunct/update documents.
- **Audit**: Every state change (Active -> Defunct -> Active) must be logged with `actor` and `reason`.
