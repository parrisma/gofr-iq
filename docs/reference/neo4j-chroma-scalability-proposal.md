# Proposal: Scaling Neo4j + Chroma to ~1,000,000 Documents

## Summary
This proposal outlines how to update the production docker-compose stack to support ~1M documents with higher resilience. It focuses on:
- Neo4j high-availability with read scaling
- Vector store scaling and resiliency
- Recommended compose changes and configuration

## Goals
- Handle ~1,000,000 documents with stable query latency
- Improve resilience to single-node failures
- Support horizontal read scaling
- Preserve existing GOFR auth + service topology

## Current State (from docker-compose.yml)
- Single Neo4j node (`gofr-neo4j`)
- Single ChromaDB node (`gofr-chromadb`)
- MCP connects directly to single nodes
- No HA, no sharding, single persistent volume

---

## Neo4j Scaling & Resilience Proposal

### Recommended Architecture
**Neo4j Causal Cluster (3 Core + 2 Read Replica)**
- 3 Core members for leader election and write availability
- 2 Read Replicas to scale read-heavy workloads (e.g., client feeds, queries)
- MCP connects via routing driver (`neo4j://`) using a load-balanced address

> **Note**: Neo4j Causal Cluster requires Neo4j Enterprise or Aura. OSS does not support clustering. If Enterprise is not available, use a single node + standby with backups (less resilient).

### Compose-Level Changes (High-Level)
1. **Replace single `neo4j` service with multiple services**:
   - `neo4j-core-1`, `neo4j-core-2`, `neo4j-core-3`
   - `neo4j-read-1`, `neo4j-read-2`

2. **Add routing/ingress endpoint**:
   - Use `neo4j://gofr-neo4j-router:7687` from MCP
   - Router can be Neo4j load balancer or HAProxy

3. **Volume separation per node**:
   - Each core + replica gets its own data + logs volume

4. **Update MCP env**:
   - `GOFR_IQ_NEO4J_URI=neo4j://gofr-neo4j-router:7687`

5. **Memory tuning**:
   - Increase heap + page cache for ~1M docs
   - Example: heap 4–8GB, page cache 8–16GB (depends on host)

### Expected Benefits
- Automatic failover for writes
- Horizontal scaling for read traffic
- Better availability during maintenance

---

## ChromaDB Scaling & Resilience Proposal

### Current Limitation
ChromaDB OSS (single-node) does **not** provide native sharding or HA. For ~1M documents:
- Single node can work if resources are sufficient
- But resilience and horizontal scaling remain limited

### Options

#### Option A: Single-Node Chroma (Minimal Change)
- Increase CPU/RAM
- Ensure persistent volume on fast SSD
- Add frequent backups + snapshotting
- Add restart policy + health checks (already present)

**Pros**: Minimal change
**Cons**: No HA, no shard scaling

#### Option B: Migrate to a Distributed Vector DB (Recommended)
Replace Chroma with a vector DB designed for sharding/HA. Suggested options:
- **Qdrant** (open-source, supports clustering)
- **Weaviate** (open-source, sharding + replication)
- **Pinecone** (managed, no infra burden)

**Pros**: Real sharding + HA
**Cons**: Requires code changes + data migration

### Compose-Level Changes (Option B Example)
- Replace `chromadb` service with a `qdrant` cluster
- Update MCP env:
  - `GOFR_IQ_CHROMADB_HOST` → new vector service hostname
  - Update embedding index client to use Qdrant/Weaviate

---

## Proposed Compose Changes (Summary)

### Neo4j
- Add multiple Neo4j nodes (3 core + 2 replicas)
- Add routing endpoint service
- Update MCP connection URI
- Add per-node volumes

### Vector Store
- Short-term: keep Chroma, increase resources + backups
- Long-term: replace with distributed vector DB and update MCP client

---

## Implementation Phases

### Phase 1 — Neo4j HA
1. Update compose to Causal Cluster
2. Adjust MCP connection to routing URI
3. Validate failover + read scaling

### Phase 2 — Chroma Resilience (short-term)
1. Increase resources
2. Add regular backups
3. Monitor latency + storage size

### Phase 3 — Vector DB Migration (long-term)
1. Choose distributed vector DB
2. Update embedding_index client
3. Migrate data (re-embed or export/import)
4. Cutover MCP to new vector backend

---

## Risks & Considerations
- Neo4j Enterprise licensing required for clustering
- Vector DB migration requires code changes + data re-ingest
- HA needs load balancers and proper network config

---

## Recommended Next Steps
1. Confirm Neo4j licensing strategy (Enterprise vs Aura)
2. Decide vector DB path (Chroma single-node vs distributed)
3. Implement compose changes in a staging environment
4. Load test at ~1M docs with representative query mix

---

# Implementation Plan (Detailed)

## 1) Neo4j (Non‑Enterprise) — Best Possible Resilience/Scale

> **Constraint**: Community/OSS Neo4j does **not** support clustering/HA. The best we can do is harden a single primary with **backups + warm standby + fast restore + read caching**.

### Phase 1 — Compose + Runtime Hardening
1. **Add dedicated standby container**
   - Add a second Neo4j service (e.g., `neo4j-standby`) using the same image.
   - Do **not** allow writes on standby (keep it stopped by default or start with `NEO4J_dbms_read__only=true`).
   - Bind it to an internal port only (no public port mapping).

2. **Add scheduled backups from primary**
   - Add a lightweight backup job container (e.g., `neo4j-backup`) using the Neo4j image or a small alpine container with `neo4j-admin`.
   - Mount a shared `gofr-iq-backups` volume.
   - Run a cron (or systemd in container) to run `neo4j-admin database dump` daily/hourly.

3. **Enable WAL + transaction log retention**
   - Ensure transaction logs persist long enough for point‑in‑time recovery.
   - Add/verify:
     - `NEO4J_dbms_tx__log_rotation_retention__policy=1G size` (or time‑based, e.g., `7 days`)

4. **Memory & cache tuning for 1M docs**
   - Increase heap + page cache in compose env:
     - `NEO4J_dbms_memory_heap_initial__size=4G`
     - `NEO4J_dbms_memory_heap_max__size=8G`
     - `NEO4J_dbms_memory_pagecache_size=8G` (adjust to host RAM)

5. **Add health checks + restart policy**
   - Increase health check retries/timeouts to tolerate longer startup.
   - Keep `restart: unless-stopped`.

### Phase 2 — Fast Restore + Failover Playbook
6. **Create restore script**
   - Add script (e.g., `scripts/neo4j_restore.sh`) to:
     - Stop primary container
     - Restore latest dump to the Neo4j data volume
     - Start primary

7. **Define manual failover procedure**
   - If primary fails, start `neo4j-standby` container and point MCP to it.
   - Update `GOFR_IQ_NEO4J_URI=bolt://gofr-neo4j-standby:7687` in environment.

8. **Add monitoring + alerting**
   - Add a lightweight metrics exporter (Neo4j has Prometheus metrics) and alert on:
     - High GC, low page cache hit ratio
     - Disk usage on data volume
     - Query latency spikes

### Phase 3 — Optional Read Offload
9. **Add a read-only replica with snapshot restore**
   - Use a separate data volume seeded from periodic dumps.
   - Start in read‑only mode for analytics queries.
   - This is **not** real-time, but can offload heavy read/report workloads.

### Deliverables (Neo4j OSS)
- Updated compose with `neo4j-standby`, backup job, tuning, and volumes
- Restore + failover scripts
- Monitoring targets + runbook

---

## 2) Migration to Qdrant Cluster (Hard Cutover, No Data Migration)

> **Goal**: Replace ChromaDB with a sharded, replicated vector DB. Since pre‑release, we can do a hard cutover with no data migration.

### Phase 0 — Preflight
1. **Confirm vector size + distance**
   - Lock embedding dimensions (e.g., 384/768/1024/1536).
   - Choose distance metric (cosine/dot) to match current embeddings.
2. **Inventory current Chroma usage**
   - Confirm collection name(s) and metadata fields in use.
   - Confirm query filters used in MCP (group/source/doc filtering).
3. **Decide Qdrant API mode**
   - HTTP only (default) or gRPC (if client supports it).
   - Decide if an API key will be required.
4. **Record current MCP vector config**
   - Capture existing Chroma env vars used by MCP.
   - Note any custom collection or namespace settings.
5. **Confirm resource baseline**
   - Validate host RAM/CPU can run 3 Qdrant nodes.
   - Ensure persistent volumes are on fast storage.
6. **Pick the Qdrant entrypoint hostname**
   - Use internal service hostname (no `localhost`).
   - Decide if a load balancer service is required.

### Phase 1 — Stand up Qdrant
2. **Choose Qdrant cluster topology**
   - Minimum: 3 nodes for quorum + replication.
   - Example services: `qdrant-1`, `qdrant-2`, `qdrant-3`.
3. **Add Qdrant services to docker-compose**
   - One volume per node (data + snapshots).
   - Cluster config: node IDs, peer URLs, API key (if used).
   - Expose one node (or add a load balancer) for MCP access.
4. **Add health checks + startup ordering**
   - Health endpoint checks for each node.
   - MCP waits for Qdrant readiness.
5. **Verify cluster health**
   - Validate node list and peer visibility.
   - Confirm single entrypoint is reachable from MCP container.

### Phase 2 — Migrate Code (Embedding Index)
6. **Install Qdrant client library**
   - Add `qdrant-client` to Python dependencies.
7. **Implement Qdrant backend**
   - Implement in `app/services/embedding_index.py` (or a new service).
   - Map operations:
     - `embed_document` → `upsert` points
     - `search` → `search` with payload filters
     - `delete_document` → `delete` by filter
8. **Define collection schema + payload indexes**
   - Payload fields: `document_guid`, `group_guid`, `source_guid`, `language`,
     `chunk_index`, `start_char`, `end_char`, `impact_score`, `impact_tier`,
     `title`, `created_at`.
   - Add payload indexes for `group_guid`, `source_guid`, `document_guid`.
9. **Idempotent collection bootstrap**
   - On MCP startup: create collection if missing, validate size + distance.
   - Fail fast if schema is incompatible.
10. **Update MCP configuration**
   - Replace Chroma host/port env vars with Qdrant host/port.
   - Remove Chroma-specific configuration paths.
11. **Update service dependencies**
   - Replace `chromadb` in MCP `depends_on` with Qdrant entrypoint.

### Phase 3 — Hard Cutover
12. **Switch MCP to Qdrant endpoint**
   - Update MCP env to point to Qdrant host/port.
   - Restart MCP service to pick up env changes.
13. **Run a minimal smoke test**
   - Ingest 10–50 docs, verify `query_documents` + `get_client_feed`.
   - Validate filtering by `group_guid` and `source_guid`.
14. **Validate collection integrity**
   - Confirm collection size and payload counts match ingestion.
   - Confirm index creation completed for filter fields.

### Phase 4 — Cleanup
15. **Remove ChromaDB service**
   - Remove `chromadb` from compose and related env vars.
16. **Update docs + scripts**
   - Replace Chroma references in scripts and docs.
   - Add Qdrant troubleshooting notes.
17. **Remove stale data volumes (optional)**
   - Remove Chroma volumes once Qdrant is stable and validated.

### Deliverables (Qdrant)
- Updated compose with Qdrant cluster + health checks
- Qdrant backend implementation with schema + indexes
- Hard‑cutover checklist + smoke test steps
