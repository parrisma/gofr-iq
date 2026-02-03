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
