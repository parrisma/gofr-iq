# GOFR-IQ Simulation Hub

**Role**: Central operational guide for the GOFR-IQ market simulation environment.

The simulation acts as a "pocket universe" to validate GOFR-IQ's core value proposition: **Intelligent Profile-based Selection (IPS)**. By generating synthetic market events (Earnings, M&A) and client portfolios (Long-Only, Hedge Fund), we prove the system can route the right story to the right client while filtering out noise.

---

## 📚 Documentation Map

| Doc | Purpose |
| :--- | :--- |
| **[Architecture & Design](architecture.md)** | Technical deep dive into the 14-node graph schema, relationships (SUPPLIES_TO, COMPETES_WITH), and client archetypes. |
| **[Validation Framework](validation.md)** | How we measure success. Intent-based testing scenarios (e.g., "Does a supplier fire alert the downstream client?"). |
| **[Neo4j Query Reference](neo4j_queries.md)** | Dictionary of Cypher queries to inspect the graph, check relationships, and debug data. |
| **[Enhancement Plan](simulation_enhancement_plan.md)** | Roadmap of completed and planned features for the simulation engine. |

---

## 🚀 Running the Simulation

### 1. Prerequisites
*   **Infrastructure**: `scripts/start-prod.sh` must be running.
*   **Tokens**: `scripts/bootstrap.py` must have generated tokens.
*   **LLM Key**: `simulation/.env.openrouter` must contain your `OPENROUTER_API_KEY`.

### 2. The Orchestrator (`run_simulation.sh`)
The recommended way to run a simulation is via the master shell script, which enforces stage gates (Auth -> Universe -> Generation -> Ingestion).

```bash
cd simulation

# Standard Run: 10 new stories
./run_simulation.sh --count 10

# Large Run: 50 stories
./run_simulation.sh --count 50

# Re-run Ingestion Only (Skip LLM Generation)
./run_simulation.sh --skip-generate
```

### 3. Clean Slate (Reset)
To wipe all data and start fresh (recommended between logical runs):

```bash
cd simulation
./reset_simulation_env.sh
# Use --force to skip confirmation prompt
```

---

## 🔬 Validation & Analysis

After a run completes, verify the results:

### Automated Validation
Runs the standard test suite (Direct Holdings, Competitor Logic, Noise Filtering).
```bash
uv run simulation/validate_feeds.py --verbose
```

### Visual Inspection (IPS Demo)
Compare how different clients see the same story side-by-side.
```bash
uv run simulation/demo_ips_filtering.py
```

### Query a Specific Fee
Inspect the raw feed for a specific client archetype.
```bash
uv run simulation/query_client_feed.py --client client-hedge-fund --limit 5
```

---

## 🛠️ Pipeline Stages (Under the Hood)

The orchestration script runs these Python modules in sequence:

1.  **Universe Loader** (`load_simulation_data.py`):
    *   Loads 16 companies, 24 instruments, 5 macro factors.
    *   Creates graph relationships (`SUPPLIES_TO`, `EXPOSED_TO`).
    *   Initialized 3 client profiles (Hedge Fund, Pension Fund, Retail).

2.  **Story Generator** (`generate_synthetic_stories.py`):
    *   Uses Claude 3.5 Sonnet to generate JSON news stories.
    *   Injects "Ground Truth" metadata (e.g., "This story *should* affect AAPL").
    *   Caches results to `simulation/test_output/` to save API costs.

3.  **Ingestion Service** (`ingest_synthetic_stories.py`):
    *   Chunks and embeds texts (ChromaDB).
    *   Ingests nodes to Neo4j.
    *   Extracts entities and links them to the graph.

---

## ⚠️ Troubleshooting

**"Gate authentication/sources failed"**
*   **Fix**: Run `uv run scripts/bootstrap.py` to regenerate tokens.

**"Gate ingestion failed"**
*   **Fix**: Check `data/logs/mcp.log`. Often caused by Neo4j connection timeouts if system load is high.

**"No stories generated"**
*   **Fix**: Ensure `simulation/.env.openrouter` exists and has credit.

**"Validation Recall is 0%"**
*   **Fix**: Run `check_documents.py` to ensure documents actually made it into the graph. If they exist but aren't found, check the `AFFECTS` relationships in Neo4j Browser.
