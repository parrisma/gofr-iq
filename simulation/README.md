# GOFR-IQ Simulation Environment

**Purpose**: Generate and test synthetic financial news for validating client-centric feed intelligence.

---

## 🚀 Quick Start

```bash
# 1. Start infrastructure
./docker/start-prod.sh

# 2. Run full simulation (universe + 10 stories)
./simulation/run_simulation.sh --count 10

# 3. Query a client's feed
./simulation/query_client_feed.py --client client-hedge-fund

# 4. Validate results
./simulation/validate_feeds.py
```

**That's it!** The orchestrator handles everything: auth, sources, universe loading, story generation, and ingestion.

---

## 📚 What Is This?

The simulation environment proves GOFR-IQ's core value proposition: **Client-Centric Retrieval-Augmented Story Selection**.

### Problem Statement
Financial professionals are drowning in noise. A hedge fund trader holding AAPL doesn't care about wheat futures. A pension fund with ESG constraints doesn't want tobacco news.

### Solution
GOFR-IQ combines:
- **Graph Intelligence**: Portfolio holdings → Document relationships
- **Semantic Search**: Vector similarity for nuanced relevance
- **IPS Filtering**: Investment Policy Statements enforce client mandates
- **Trust Gating**: High-trust sources for conservative clients, rumors for aggressive traders

### Validation Goals
1. **Precision**: Client with AAPL position sees AAPL news (not random stocks)
2. **Propagation**: Client with GTX sees news about QNTM (GTX's supplier)
3. **Trust Gating**: Pension fund (min_trust=8) filters low-trust rumors
4. **IPS Enforcement**: ESG-constrained client doesn't see tobacco stories

---

## 🏗️ Components

### Core Scripts (Orchestrated)
- **`run_simulation.sh`** - Master orchestrator (auth → universe → stories → ingestion)
- **`reset_simulation_env.sh`** - Clean slate (wipes Neo4j, ChromaDB, storage)

### Generation
- **`generate_synthetic_stories.py`** - LLM-powered story generation with validation metadata
- **`generate_client_ips.py`** - Investment Policy Statement generation

### Loading
- **`ingest_synthetic_stories.py`** - Document ingestion (Neo4j + ChromaDB)
- **`load_simulation_data.py`** - Consolidated universe + clients loader
- **`setup_neo4j_constraints.py`** - Schema constraints

### Query & Validation
- **`query_client_feed.py`** - CLI for querying client feeds
- **`validate_feeds.py`** - Automated validation harness
- **`client_profiler.py`** - IPS-based filtering & reranking
- **`demo_ips_filtering.py`** - IPS demo (shows filtering in action)

### Data
- **`universe/builder.py`** - Mock universe (16 companies, relationships, factors)
- **`client_ips/*.json`** - Investment Policy Statements
- **`test_output/*.json`** - Generated synthetic stories
- **`tokens.json`** - Cached auth tokens

---

## 📖 Documentation Index

### Operational
- **[OPERATIONAL_GUIDE.md](OPERATIONAL_GUIDE.md)** - Step-by-step SOP for running simulations
  - Prerequisites, workflows, troubleshooting
  - Manual vs orchestrated runs
  - Stage gate validation

### Technical
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design & rationale
  - Universe model (companies, relationships, factors)
  - Client archetypes & portfolios
  - IPS architecture (external JSON, filtering logic)
  - Graph schema & feed intelligence

### Testing
- **[VALIDATION.md](VALIDATION.md)** - Test results & status
  - Phase completion status
  - Validation scenarios & pass rates
  - IPS demo results
  - Known issues & next steps

### Planning (Archive)
- **[archive/planning/](archive/planning/)** - Historical analysis documents
  - Gap analysis, enhancement proposals
  - Useful for understanding evolution

---

## 🎯 Common Operations

### Reset Environment
```bash
./simulation/reset_simulation_env.sh --force
```
Wipes Neo4j, ChromaDB, and storage. Use before running new simulation to avoid data contamination.

### Generate Stories Only
```bash
uv run simulation/generate_synthetic_stories.py --count 50 --output-dir test_output/
```
Generates synthetic stories without ingestion. Useful for reviewing content before loading.

### Query Client Feed
```bash
# Hedge fund (aggressive, min_trust=2)
./simulation/query_client_feed.py --client client-hedge-fund --limit 20

# Pension fund (conservative, min_trust=8)
./simulation/query_client_feed.py --client client-pension-fund --limit 20

# Retail trader (permissive, min_trust=1)
./simulation/query_client_feed.py --client client-retail --limit 20
```

### Validate Feed Quality
```bash
# Run full validation suite
./simulation/validate_feeds.py

# Validate specific client
./simulation/validate_feeds.py --client client-hedge-fund
```

### Demo IPS Filtering
```bash
# Shows how same documents get filtered differently per client
uv run simulation/demo_ips_filtering.py
```

### Check Data State
```bash
# Count documents
uv run simulation/check_documents.py

# Check story cache
uv run simulation/check_cache.py
```

---

## 🏛️ Architecture Highlights

### Universe Model
- **16 Companies**: OmniCorp, QuantumTech, BankOne, VelocityMotors, etc.
- **Relationships**: SUPPLIES_TO, COMPETES_WITH, PARTNER_OF, EXPOSED_TO
- **Factors**: Interest rates, commodity prices, regulation, consumer sentiment
- **Clients**: 3 archetypes (hedge fund, pension fund, retail)

### Story Generation
- **LLM-Powered**: Claude generates realistic financial narratives
- **Scenario-Based**: Direct holdings, supply chain, competitor, macro, ESG
- **Validation Metadata**: Each story tagged with expected clients, relationship hops
- **Caching**: Reuses generated stories to save API costs

### Feed Intelligence
1. **Graph Traversal**: `(Client)-[:HOLDS]->(Instrument)<-[:AFFECTS]-(Document)`
2. **Semantic Search**: ChromaDB finds similar content via embeddings
3. **Trust Filtering**: Filter by source trust level (min_trust from ClientProfile)
4. **IPS Enforcement**: Sector exclusions, ESG concerns, theme alignment
5. **Hybrid Scoring**: Combines graph distance + similarity + trust + recency

---

## 🎓 Learning Path

### New Users
1. Read [OPERATIONAL_GUIDE.md](OPERATIONAL_GUIDE.md) - Understand workflow
2. Run `./simulation/run_simulation.sh --count 5` - See it work
3. Query feeds: `./simulation/query_client_feed.py --client client-hedge-fund`
4. Review [ARCHITECTURE.md](ARCHITECTURE.md) - Understand the "why"

### Developers
1. Study `universe/builder.py` - Mock universe structure
2. Review `generate_synthetic_stories.py` - LLM prompting patterns
3. Trace `query_client_feed.py` - Feed query logic
4. Read [VALIDATION.md](VALIDATION.md) - Test scenarios

### Traders/Business Users
1. Run `./simulation/demo_ips_filtering.py` - See IPS in action
2. Review `client_ips/*.json` - Example Investment Policy Statements
3. Query different clients - See personalization
4. Read [ARCHITECTURE.md](ARCHITECTURE.md) "IPS Architecture" section

---

## 🔧 Troubleshooting

**Issue**: "Neo4j connection failed"  
**Fix**: Ensure infrastructure is running: `./docker/start-prod.sh`

**Issue**: "No documents in feed"  
**Fix**: Run ingestion: `./simulation/run_simulation.sh --count 10`

**Issue**: "Stories not generating"  
**Fix**: Check OpenRouter API key: `cat simulation/.env.openrouter`

**Issue**: "Validation failures"  
**Fix**: See [VALIDATION.md](VALIDATION.md) for known issues and expected pass rates

**Issue**: "Out of sync"  
**Fix**: Full reset: `./simulation/reset_simulation_env.sh --force && ./simulation/run_simulation.sh --count 10`

---

## 📊 Current Status

### Phase Completion
- ✅ **Phase 1-2**: Universe & client generation (Complete)
- ✅ **Phase 3**: Enhanced story generation with validation metadata (Complete)
- ✅ **Phase 4**: Validation harness (Complete - 25% pass rate baseline)
- ✅ **Phase 5.1-5.2**: IPS generation & ClientProfiler (Complete)
- 🅿️ **Phase 5.4-5.5**: LLM reranker & entity resolution (Parked)

### Validation Results
- **Competitor Awareness**: 100% (2/2 passed)
- **False Positive Prevention**: 94% (30/32 passed)
- **Direct Holdings**: 20% (3/15 passed - needs improvement)
- **Supply Chain**: 20% (1/5 passed - needs debugging)
- **Overall**: 25% baseline (6/24 assertions)

See [VALIDATION.md](VALIDATION.md) for detailed results.

---

## 🚧 Known Limitations

1. **Supply Chain Propagation**: 20% pass rate - relationship traversal needs refinement
2. **Direct Holdings**: 20% pass rate - portfolio matching needs improvement
3. **Entity Resolution**: Aliases generated but not systematically validated
4. **LLM Reranking**: Keyword-based theme matching (semantic understanding parked)

---

## 🎯 Next Steps

1. **Improve Validation**: Debug supply chain and direct holdings scenarios
2. **Scale Testing**: Run with 100+ documents to stress test
3. **IPS Integration**: Wire IPS filtering into MCP `get_client_feed` tool
4. **Production Readiness**: Add monitoring, error handling, retry logic

---

## 📞 Support

- **Documentation**: See other .md files in this directory
- **Code Issues**: Check `check_documents.py` and `check_cache.py` for diagnostics
- **Architecture Questions**: Read [ARCHITECTURE.md](ARCHITECTURE.md)
- **Operational Issues**: See [OPERATIONAL_GUIDE.md](OPERATIONAL_GUIDE.md) troubleshooting section

---

**Last Updated**: 2026-01-18  
**Version**: Post-consolidation v1.0
