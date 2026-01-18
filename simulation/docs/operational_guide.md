# GOFR-IQ Simulation - Operational Guide

**Purpose**: Step-by-step procedures for running simulations, validating results, and troubleshooting issues.

---

## Prerequisites

### 1. Infrastructure Running
```bash
# Start production stack (Neo4j, ChromaDB, Vault)
./docker/start-prod.sh

# Verify services are up
docker ps | grep -E "neo4j|chroma|vault"
```

### 2. Bootstrap Configuration
```bash
# Generate tokens and config (first time only)
uv run scripts/bootstrap.py

# Verify files exist
ls config/generated/bootstrap_tokens.json
ls docker/.env
```

### 3. OpenRouter API Key
```bash
# Set API key for LLM story generation
echo "OPENROUTER_API_KEY=your_key_here" > simulation/.env.openrouter

# Verify
cat simulation/.env.openrouter
```

---

## Standard Workflow (6 Steps)

### Step 0: Clean Slate (Recommended)

**When**: Before starting a new simulation run to avoid data contamination.

```bash
cd simulation
./reset_simulation_env.sh
```

**Confirmation Required**: Type `yes` unless using `--force` flag.

**What It Does**:
- Wipes all Neo4j nodes and relationships
- Clears ChromaDB collections
- Removes `data/storage/` simulation files

**Warning**: This is destructive. Use `--force` for automation:
```bash
./reset_simulation_env.sh --force
```

---

### Steps 1-4: Orchestrated Run

**The Fast Path**: Use `run_simulation.sh` to automate Steps 1-4.

```bash
cd simulation

# Run with 10 stories
./run_simulation.sh --count 10

# Run with 50 stories
./run_simulation.sh --count 50

# Dry run (no story generation)
./run_simulation.sh --count 0
```

**What It Does**:

**Step 1: Foundation (Auth & Sources)**
- Creates Vault groups: `apac-sales`, `reuters-feed`, `bloomberg-feed`, etc.
- Generates auth tokens
- Registers news sources in MCP registry

**Step 2: Universe (Graph Loading)**
- Loads 16 companies to Neo4j (OmniCorp, QuantumTech, BankOne, etc.)
- Creates 24 instruments (tickers)
- Adds 5 macro factors (interest rates, commodity prices, etc.)
- Creates relationships: SUPPLIES_TO, COMPETES_WITH, EXPOSED_TO
- Loads 3 client archetypes with portfolios

**Step 3: Story Generation**
- Generates synthetic news via Claude LLM
- Uses cached stories when available (saves API costs)
- Adds validation metadata: expected clients, relationship hops
- Outputs to `test_output/synthetic_*.json`

**Step 4: Ingestion**
- Ingests documents to Neo4j (Document nodes)
- Creates embeddings in ChromaDB
- Extracts entities and relationships (AFFECTS, MENTIONS)
- Links documents to instruments and events

**Stage Gates**: After each step, the orchestrator validates:
- Groups exist
- Tokens work
- Universe loaded
- Stories generated
- Documents ingested

---

### Step 5: Metrics & Validation

**Query Client Feeds**:
```bash
# Hedge fund (aggressive, min_trust=2)
./query_client_feed.py --client client-hedge-fund --limit 20

# Pension fund (conservative, min_trust=8)
./query_client_feed.py --client client-pension-fund --limit 20

# Retail trader (permissive, min_trust=1)
./query_client_feed.py --client client-retail --limit 20
```

**Run Validation Suite**:
```bash
# Automated validation
./validate_feeds.py

# Verbose output
./validate_feeds.py --verbose

# Specific client
./validate_feeds.py --client client-hedge-fund
```

**Demo IPS Filtering**:
```bash
# Shows filtering differences across clients
uv run demo_ips_filtering.py
```

---

### Step 6: Review Results

**Check Document Counts**:
```bash
uv run check_documents.py
```

**Expected Output**:
```
Documents in Neo4j: 50
Documents in ChromaDB: 150-200 (includes chunks)
Sources: 5
Clients: 3
Companies: 16
Relationships: 200+
```

**Check Story Cache**:
```bash
uv run check_cache.py
```

**Validation Results**:
- See [VALIDATION.md](VALIDATION.md) for expected pass rates
- Current baseline: 25% overall, 100% competitor, 94% false positive

---

## Manual Steps (Advanced)

### Generate Stories Only
```bash
uv run generate_synthetic_stories.py \
  --count 50 \
  --output-dir test_output/ \
  --cache-dir test_output/
```

**Options**:
- `--count`: Number of stories to generate
- `--output-dir`: Where to save stories
- `--cache-dir`: Check for existing stories first
- `--force`: Regenerate even if cached

**Use Case**: Review story content before ingestion, test LLM prompts.

### Ingest Stories Only
```bash
uv run ingest_synthetic_stories.py \
  --input-dir test_output/ \
  --group apac-sales
```

**Options**:
- `--input-dir`: Directory containing `synthetic_*.json` files
- `--group`: Group to assign documents to
- `--force`: Reingest even if already ingested

**Use Case**: Reingest after schema changes, test ingestion performance.

### Load Universe Only
```bash
uv run load_simulation_data.py
```

**What It Loads**:
- Companies, instruments, sectors
- Relationships: SUPPLIES_TO, COMPETES_WITH, PARTNER_OF
- Factors: Interest rates, commodity prices, regulation
- Factor exposures: EXPOSED_TO with beta values
- Clients: 3 archetypes with portfolios and watchlists

**Use Case**: Test graph queries without ingesting documents using the consolidated loader.

### Generate IPS Only
```bash
uv run generate_client_ips.py
```

**Output**: `client_ips/ips_*.json` for each client archetype.

**Use Case**: Customize IPS policies, test filtering logic.

### Setup Constraints Only
```bash
uv run setup_neo4j_constraints.py
```

**Creates**: Unique constraints on GUIDs for all node types.

**Use Case**: Run after Neo4j reset, ensure data integrity.

---

## Troubleshooting

### Issue: "Neo4j connection refused"
**Symptoms**: `ConnectionRefusedError` or `Neo4j.ClientError.Security.Unauthorized`

**Diagnosis**:
```bash
# Check if Neo4j is running
docker ps | grep neo4j

# Check Neo4j logs
docker logs gofr-neo4j
```

**Fix**:
```bash
# Restart infrastructure
./docker/start-prod.sh

# Verify connection
curl -u neo4j:$NEO4J_PASSWORD http://localhost:7474
```

---

### Issue: "ChromaDB collection not found"
**Symptoms**: `CollectionNotFoundError` or empty search results

**Diagnosis**:
```bash
# Check ChromaDB logs
docker logs gofr-chromadb

# Verify collections exist
uv run check_documents.py
```

**Fix**:
```bash
# Reingest documents
./simulation/run_simulation.sh --count 10
```

---

### Issue: "No stories generated"
**Symptoms**: `test_output/` directory empty or no new files

**Diagnosis**:
```bash
# Check OpenRouter API key
cat simulation/.env.openrouter

# Test API access
curl https://openrouter.ai/api/v1/models \
  -H "Authorization: Bearer $OPENROUTER_API_KEY"
```

**Fix**:
```bash
# Set valid API key
echo "OPENROUTER_API_KEY=sk-or-..." > simulation/.env.openrouter

# Regenerate
uv run generate_synthetic_stories.py --count 5 --force
```

---

### Issue: "Validation failures"
**Symptoms**: Low pass rates (<50%) in validate_feeds.py

**Diagnosis**:
```bash
# Run validation with verbose output
./validate_feeds.py --verbose

# Check specific scenario
./validate_feeds.py --scenario direct_holdings
```

**Expected Behavior**:
- Competitor: 100% (should always work)
- False Positives: 94% (near-perfect filtering)
- Direct Holdings: 20-30% (known issue - portfolio matching)
- Supply Chain: 20-30% (known issue - relationship traversal)

**Fix**: See [VALIDATION.md](VALIDATION.md) for known issues and remediation plans.

---

### Issue: "Feed returns no documents"
**Symptoms**: `query_client_feed.py` returns empty results

**Diagnosis**:
```bash
# Check if documents exist
uv run check_documents.py

# Check if client exists
./query_client_feed.py --client client-hedge-fund
```

**Fix**:
```bash
# Full reset and reload
./reset_simulation_env.sh --force
./run_simulation.sh --count 10
```

---

### Issue: "Out of sync errors"
**Symptoms**: Validation fails, inconsistent results, orphaned data

**Diagnosis**: Data from multiple simulation runs mixed together.

**Fix**: Full reset
```bash
# Nuclear option: wipe everything
./reset_simulation_env.sh --force

# Reload fresh
./run_simulation.sh --count 10

# Validate
./validate_feeds.py
```

---

## Performance Considerations

### Story Generation Time
- **Per Story**: ~30-60 seconds (LLM generation)
- **10 Stories**: ~5-10 minutes
- **50 Stories**: ~25-50 minutes
- **With Caching**: <1 minute (reuses existing)

**Optimization**: Use `--cache-dir` to reuse stories across runs.

### Ingestion Time
- **Per Document**: ~2-5 seconds (entity extraction)
- **10 Documents**: ~20-50 seconds
- **50 Documents**: ~2-4 minutes

**Bottleneck**: LLM entity extraction (can't be parallelized easily).

### Query Time
- **Simple Feed**: <1 second (graph traversal)
- **Hybrid Search**: 1-3 seconds (ChromaDB + Neo4j)
- **With IPS**: +100-500ms (filtering overhead)

---

## Automation Tips

### Cron Job Example
```bash
# Daily simulation run
0 2 * * * cd /home/gofr/devroot/gofr-iq && ./simulation/run_simulation.sh --count 10 >> /var/log/gofr-sim.log 2>&1
```

### CI/CD Integration
```yaml
# GitHub Actions example
- name: Run Simulation
  run: |
    ./docker/start-prod.sh
    ./simulation/run_simulation.sh --count 5
    ./simulation/validate_feeds.py
```

### Parameterized Runs
```bash
# Environment-driven
export STORY_COUNT=50
export CLIENT_ARCHETYPE=hedge-fund
./simulation/run_simulation.sh --count $STORY_COUNT
./simulation/query_client_feed.py --client client-$CLIENT_ARCHETYPE
```

---

## Best Practices

### 1. Always Reset Before Major Runs
```bash
./reset_simulation_env.sh --force
```
Prevents data contamination from previous runs.

### 2. Use Story Caching
```bash
# First run: Generates stories
./run_simulation.sh --count 50

# Subsequent runs: Reuses stories
./run_simulation.sh --count 50
```
Saves API costs and time.

### 3. Validate After Changes
```bash
# After code changes
./run_simulation.sh --count 10
./validate_feeds.py
```
Ensures changes don't break feed logic.

### 4. Monitor Resource Usage
```bash
# Check Neo4j memory
docker stats gofr-neo4j

# Check ChromaDB disk usage
du -sh data/chromadb/
```

### 5. Regular Full Resets
```bash
# Weekly clean slate
./reset_simulation_env.sh --force
./run_simulation.sh --count 50
```
Prevents drift and accumulation of test artifacts.

---

## Stage Gate Validation

The orchestrator (`run_simulation.sh`) enforces stage gates to ensure data quality:

### After Step 1 (Foundation)
- ✅ Groups exist in Vault
- ✅ Tokens generated and cached
- ✅ Sources registered in MCP

### After Step 2 (Universe)
- ✅ Companies loaded (expect 16)
- ✅ Instruments loaded (expect 24)
- ✅ Factors loaded (expect 5)
- ✅ Clients loaded (expect 3)
- ✅ Relationships created (expect 100+)

### After Step 3 (Generation)
- ✅ Stories generated (expect N matching --count)
- ✅ Validation metadata present
- ✅ No duplicate titles

### After Step 4 (Ingestion)
- ✅ Documents in Neo4j (expect N)
- ✅ Embeddings in ChromaDB (expect 3*N for chunking)
- ✅ Relationships created (AFFECTS, MENTIONS)

**If Any Gate Fails**: Orchestrator stops and reports error.

---

## Quick Reference

### Most Common Commands
```bash
# Full run
./reset_simulation_env.sh --force && ./run_simulation.sh --count 10

# Query hedge fund feed
./query_client_feed.py --client client-hedge-fund

# Validate
./validate_feeds.py

# Demo IPS
uv run demo_ips_filtering.py

# Check state
uv run check_documents.py
```

### File Locations
- Stories: `test_output/synthetic_*.json`
- IPS: `client_ips/ips_*.json`
- Tokens: `tokens.json`
- Logs: Check orchestrator output

### Useful Cypher Queries
```cypher
// Count all nodes by label
MATCH (n) RETURN labels(n), count(*)

// Show client portfolios
MATCH (c:Client)-[:HOLDS]->(i:Instrument)
RETURN c.name, collect(i.ticker)

// Show document relationships
MATCH (d:Document)-[r:AFFECTS]->(i:Instrument)
RETURN d.title, i.ticker, r.magnitude
LIMIT 10
```

---

**Last Updated**: 2026-01-18  
**Version**: Post-consolidation v1.0
