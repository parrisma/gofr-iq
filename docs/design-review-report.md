# Deep Functional & Technical Design Review: GOFR-IQ

**Date:** December 9, 2025  
**Target System:** GOFR-IQ (APAC Brokerage News Repository)  
**Reviewer:** GitHub Copilot (Gemini 3 Pro)

---

## 1. Executive Summary

**System Maturity Assessment:**  
The `gofr-iq` system demonstrates a high level of maturity for a pre-production system, evidenced by a comprehensive test suite (~700 tests) and a well-structured modular architecture. The separation of concerns between `DocumentStore` (Canonical), `EmbeddingIndex` (Vector), and `GraphIndex` (Relationships) is sound. However, the complexity of maintaining consistency across three distinct storage engines (File System, ChromaDB, Neo4j) presents the primary technical risk.

**Top 5 Critical Risks:**
1.  **Ingestion Consistency:** The current synchronous ingest pipeline (`IngestService`) writes to the canonical store and then indexes. A failure in the indexing step (Neo4j/Chroma) after the file write leaves the system in an inconsistent state (document exists but is unsearchable).
2.  **Performance Bottlenecks:** Synchronous embedding generation and graph node creation during the HTTP request cycle will likely violate latency SLOs under load.
3.  **Graph/Vector Drift:** Without a robust, automated reconciliation mechanism, the graph and vector indices will drift from the canonical store over time due to partial failures or manual interventions.
4.  **Concurrency in Deduplication:** The `DuplicateDetector` relies on existing state. Concurrent requests for the same document might bypass detection if they interleave before the first write completes.
5.  **Error Handling Granularity:** Current error handling in `IngestService` may not distinguish sufficiently between "retryable" (network blip) and "fatal" (schema violation) errors for downstream consumers.

**Recommended Priority Actions:**
*   Implement a "Compensation" or "Rollback" mechanism for failed ingestions in Phase 1.
*   Formalize the "Index Rebuild" strategy into a core service, not just an admin script.
*   Introduce async processing for the indexing phase to decouple ingest latency from embedding generation.

---

## 2. Detailed Review Report

### 2.1 Architecture & Data Consistency
*   **Current State:** Canonical data lives in `data/documents/` (JSON). Derived state lives in ChromaDB and Neo4j.
*   **Issues:** The "Source of Truth" pattern is correct, but the mechanism to propagate changes is synchronous.
*   **Remediation:** Ensure the `DocumentStore` is strictly append-only. Implement an "Event Log" or "Outbox Pattern" if moving to async processing, or strictly enforce a "Repair on Read" or "Background Repair" process.

### 2.2 Ingestion Pipeline (`IngestService`)
*   **Current State:** `Validate -> Deduplicate -> Store -> (Planned: Embed -> Graph)`.
*   **Issues:**
    *   **Partial Failure:** If `GraphIndex.create_node` fails, the file remains on disk.
    *   **Deduplication:** `DuplicateDetector` likely scans the index. If the index is lagging or inconsistent, duplicates will slip through.
*   **Remediation:**
    *   Wrap the multi-step ingest in a logical transaction or try/catch block that attempts to delete the canonical file if indexing fails (Compensating Transaction).
    *   Use a file-lock or database-lock on the `duplicate_hash` during ingestion to prevent race conditions.

### 2.3 Indexing & Retrieval (`QueryService`)
*   **Current State:** Hybrid search combining Vector (Chroma) + Graph (Neo4j) + Metadata.
*   **Issues:**
    *   **Scoring:** `ScoringWeights` (Semantic vs. Keyword vs. Graph) are hardcoded defaults.
    *   **Graph Traversal:** Unbounded graph traversals (e.g., "Find all news for Sector X") can be slow if not limited by depth or date.
*   **Remediation:**
    *   Expose `ScoringWeights` as dynamic configuration per query (already partially implemented, verify defaults).
    *   Enforce strict limits on Neo4j traversal depth (e.g., `max_depth=2`).

### 2.4 Security (`GroupAccessService`)
*   **Current State:** Token-based access with `GroupClaims`.
*   **Issues:** Security seems robust at the service layer.
*   **Remediation:** Ensure that *every* query to ChromaDB and Neo4j includes the `group_guid` filter clause. It is critical that this filter is applied *inside* the database query, not in application memory, to prevent data leakage.

### 2.5 Observability
*   **Current State:** `AuditService` logs events to JSONL.
*   **Issues:** JSONL on disk is hard to query in real-time for operational alerts.
*   **Remediation:** Ensure `AuditService` also emits structured logs to stdout for container log collectors (e.g., Fluentd/Datadog) to pick up.

---

## 3. Phased Remediation Plan

### Phase 1: Stabilization (Critical Fixes)
*Goal: Ensure data integrity and handle partial failures.*

*   **Task 1.1: Ingest Transactionality**
    *   **Action:** Modify `IngestService.ingest` to catch exceptions during the Indexing phase (Chroma/Neo4j). If an error occurs, attempt to delete the newly created JSON file from `DocumentStore` to maintain atomicity.
    *   **Acceptance Criteria:** A simulated Neo4j failure during ingest results in *no* new file in `data/documents`.
*   **Task 1.2: Group Filter Enforcement**
    *   **Action:** Audit `EmbeddingIndex.query` and `GraphIndex.query` to ensure `group_guid` is a mandatory parameter and is applied as a native filter.
    *   **Acceptance Criteria:** A query with `group_A` token returns 0 results for documents in `group_B`, even if they match semantically.
*   **Task 1.3: Deduplication Locking**
    *   **Action:** Implement a simple file-based lock or mutex based on the document hash during the ingest process.
    *   **Acceptance Criteria:** Two concurrent requests with identical content result in exactly one success and one "Duplicate" response.

### Phase 2: Hardening & Performance
*Goal: Improve reliability and query speed.*

*   **Task 2.1: Index Reconciliation Tool**
    *   **Action:** Implement the `IndexManager` service (as planned in Phase 14) to scan `DocumentStore` and verify presence in Chroma/Neo4j.
    *   **Acceptance Criteria:** Running `rebuild_index --verify` reports exactly which GUIDs are missing from indices.
*   **Task 2.2: Embedding Chunking Optimization**
    *   **Action:** Review `ChunkConfig`. Ensure `chunk_overlap` is sufficient to capture context across boundaries.
    *   **Acceptance Criteria:** Long documents (>20k tokens) are successfully chunked and retrievable by queries matching text at chunk boundaries.
*   **Task 2.3: Caching**
    *   **Action:** Add a short-lived TTL cache (e.g., 60s) for `QueryService` results to handle bursty read traffic.

### Phase 3: Scale & Features (Future)
*Goal: Support high throughput and advanced search.*

*   **Task 3.1: Async Ingestion**
    *   **Action:** Decouple ingestion. API accepts doc -> writes to Queue -> Worker writes to Store & Indexes.
*   **Task 3.2: Elasticsearch Integration**
    *   **Action:** Implement the optional Elasticsearch phase for advanced keyword filtering if metadata filtering in Chroma proves too slow.

---

## 4. Test Augmentation Plan

### 4.1 Existing Tests to Reuse
*   `test/test_ingest_service.py`: Reuse basic flow tests.
*   `test/test_query_service.py`: Reuse hybrid search logic tests.
*   `test/test_group_access.py`: Critical for regression testing security.

### 4.2 New Tests to Add
*   **`test_ingest_rollback_on_failure`**: Mock a failure in `EmbeddingIndex` and assert `DocumentStore` is empty.
*   **`test_concurrent_ingest_deduplication`**: Use `pytest-xdist` or `asyncio.gather` to fire simultaneous ingest requests for the same content.
*   **`test_cross_group_leakage`**: Explicitly insert a doc in Group A, query with Group B token, assert 0 results (at the DB layer).
*   **`test_rebuild_missing_index`**: Delete a doc from Chroma (but keep in FileStore), run `IndexManager.rebuild`, assert doc reappears in Chroma.

---

## 5. Metrics & SLOs

| Metric | Target SLO | Alert Threshold |
|--------|------------|-----------------|
| **Ingest Latency** | P95 < 2 seconds | > 5 seconds |
| **Query Latency** | P95 < 500 ms | > 1 second |
| **Index Freshness** | < 5 seconds (Time from Ingest to Searchable) | > 30 seconds |
| **Error Rate** | < 0.1% of requests | > 1% |
| **Consistency** | 0 missing docs in Index vs Store | > 0 detected |

---

## 6. Risk Register

| Risk ID | Risk Description | Likelihood | Impact | Mitigation |
|---------|------------------|------------|--------|------------|
| R-01 | **Partial Write Failure** (File written, Index failed) | Medium | High | Implement "Compensating Transaction" (Rollback) in Phase 1. |
| R-02 | **Neo4j Connection Loss** | Low | High | Implement circuit breaker and automatic retries in `GraphIndex`. |
| R-03 | **Large Document OOM** | Low | Medium | Enforce strict 20k word limit; stream processing for chunking. |
| R-04 | **Token Leakage** | Very Low | Critical | Rotate JWT secrets; strict logging redaction. |

---

## 7. PR / Release Checklist

- [ ] **Tests**: Run `scripts/run_tests.sh` (Must pass 100%).
- [ ] **Lint**: Run `ruff check .` and `mypy .`.
- [ ] **Security**: Verify `GOFRIQ_JWT_SECRET` is set and not default.
- [ ] **Infrastructure**: Check Neo4j and ChromaDB connectivity.
- [ ] **Data**: Run `scripts/storage_manager.sh verify` to ensure index consistency.
- [ ] **Docs**: Update `IMPLEMENTATION.md` if architecture changed.

---

## 8. Appendix: Validation Queries

**Cypher: Find Orphan Documents (No Source)**
```cypher
MATCH (n:NewsStory)
WHERE NOT (n)-[:PRODUCED_BY]->(:Source)
RETURN n.guid, n.created_at
```

**Cypher: Check Source Lineage**
```cypher
MATCH (s:Source)<-[:PRODUCED_BY]-(n:NewsStory)
RETURN s.name, count(n) as story_count
ORDER BY story_count DESC
```

**Python: Verify Vector Consistency**
```python
def verify_consistency(doc_store, chroma_index):
    file_guids = set(doc_store.list_all_guids())
    chroma_guids = set(chroma_index.get_all_ids())
    missing = file_guids - chroma_guids
    if missing:
        print(f"CRITICAL: {len(missing)} documents missing from Vector Index: {missing}")
```
