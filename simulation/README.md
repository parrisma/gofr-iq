# GOFR-IQ simulation

Purpose
- Populate a realistic, self-contained graph/vector dataset (universe, clients, documents) for validation.
- Run repeatable baseline tests that show, with a high degree of confidence, that GOFR-IQ routes valuable documents to the right client profiles and filters noise.

This folder contains two complementary test modes:
1) Deterministic "golden set" tests (recommended for regression confidence).
2) LLM-driven synthetic generation + ingestion (recommended for end-to-end realism and extraction stress).


## Quick start (recommended, deterministic)

From repo root:

1) Bring up prerequisites (Vault, AppRole creds, core secrets):

   ./scripts/bootstrap_gofr_iq.sh

2) Run the avatar feed UAT using the deterministic golden test set:

   ./simulation/run_avatar_simulation.sh --test-set --report-json tmp/avatar_report.json --report-md tmp/avatar_report.md

3) Optionally compare against the saved golden baseline:

   uv run simulation/scripts/golden_baseline.py diff --current tmp/avatar_report.json


## What is in here

Entry points
- run_avatar_simulation.sh: end-to-end UAT pipeline (reset, ingest, validate). Supports "golden set" injection.
- run_simulation.sh: thin wrapper around run_simulation.py (creates auth artifacts, loads universe/clients, generates/ingests docs, runs stage gates).
- reset_simulation_env.sh: soft reset (wipes Neo4j, ChromaDB, storage) without rebuilding containers.

Core pipeline
- run_simulation.py: orchestrates auth setup, source registration, universe/client load, story generation, ingestion, and stage gates.
- load_simulation_data.py: loads universe + synthetic clients into Neo4j using MCP scripts.
- generate_synthetic_stories.py: generates LLM-driven stories with ground truth validation metadata.
- ingest_synthetic_stories.py: ingests story JSONs via manage_document tooling.

Validation and analysis
- validate_avatar_feeds.py: queries MCP avatar feeds (MAINTENANCE + OPPORTUNITY) and asserts invariants.
- scripts/validate_test_set.py: golden test matrix runner (the most "certain" baseline tests).
- scripts/extraction_accuracy_report.py: compares expected impacts in generated stories vs what landed in Neo4j.
- validate_feeds.py: validates classic feed routing behaviors (holdings, supply chain, competitor, macro, trust gating).
- query_client_feed.py: inspect a client's "classic" feed directly from Neo4j.

Data
- universe/: deterministic universe topology (tickers, relationships, factors, exposures).
- client_ips/: example IPS JSON profiles (used by profiler demos).
- test_output/: cached generated stories (LLM mode).
- test_data/avatar_test_set.json: deterministic documents for golden set injection.
- test_data/golden_baseline.json: last saved golden baseline results.


## Prerequisites and assumptions

- Use Docker service names on gofr-net (no localhost). Examples used here:
  - Vault: http://gofr-vault:8201
  - Neo4j: bolt://gofr-neo4j:7687
  - ChromaDB: gofr-chromadb:8000

- Package/tooling: UV only.
- Credentials:
  - The LLM key is expected to be available via the normal GOFR-IQ runtime configuration (Vault-backed by default; env override is supported in some paths).
  - Simulation creates and writes tokens to simulation/tokens.json. Treat this file as sensitive.


## Workflows

### A) Deterministic baseline tests (golden set)

Goal: repeatable, high-certainty signal that "valuable docs surface for the right client profiles".

Run:

  ./simulation/run_avatar_simulation.sh --test-set --require-nonempty --min-pass-rate 0.9 --report-json tmp/avatar_report.json --report-md tmp/avatar_report.md

Notes
- The deterministic documents are defined in simulation/test_data/avatar_test_set.json.
- Data injection bypasses LLM extraction (see simulation/scripts/inject_test_data.py).
- Validation is performed via MCP tool calls (see simulation/scripts/validate_test_set.py).

Golden baseline management
- Save current results as the new golden baseline:

  uv run simulation/scripts/golden_baseline.py save --from tmp/avatar_report.json

- Diff current results vs golden:

  uv run simulation/scripts/golden_baseline.py diff --current tmp/avatar_report.json


### B) End-to-end realism (LLM generation + ingestion)

Goal: stress the full pipeline (generation, ingestion, extraction, graph wiring, trust gating).

Run 200 docs:

  ./simulation/run_avatar_simulation.sh --count 200 --report-json tmp/avatar_uat.json

Run the classic feed validation:

  uv run simulation/validate_feeds.py --verbose

Extraction accuracy report (expected vs actual in Neo4j):

  uv run simulation/scripts/extraction_accuracy_report.py --report-json tmp/extraction_accuracy.json


### C) Populate data only (universe + clients + sources, no docs)

Goal: create the universe and client set so you can manually ingest or run partial tests.

  ./simulation/run_simulation.sh --validate-only


## Current state and known gaps

- Grouping: the simulation currently uses a single group (group-simulation) as the default container for all simulation data.
  - If you need multi-group testing (cross-group isolation), the extension point is run_simulation.py (discover_simulation_requirements, token minting, and story upload_as_group).

- Certainty: prefer the golden set tests for regression confidence. The LLM-driven mode is useful for realism but will always have some nondeterminism.


## Docs

- docs/operational_guide.md
- docs/architecture.md
- docs/validation.md
- docs/neo4j_queries.md
- docs/simulation_enhancement_plan.md

---

## 🔧 Troubleshooting

**Issue**: "Neo4j connection failed"  
**Fix**: Ensure infrastructure is running: `./scripts/start-prod.sh`

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
