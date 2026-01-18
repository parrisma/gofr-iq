# How to Run a Full Simulation

This guide details the standard operating procedure for running an end-to-end market simulation in GOFR-IQ. It is designed for both human operators and automated agents (LLMs).

## Overview

The simulation pipeline consists of **6 distinct steps**, enforced by "Stage Gates" to ensure data integrity.

| Step | Name | Description | Script / Tool |
| :--- | :--- | :--- | :--- |
| **0** | **Clean Slate** | Wipe graph and vector DBs to ensure a fresh start. | `./simulation/reset_simulation_env.sh` |
| **1** | **Foundation** | Create Auth Groups, Tokens, and Register Sources. | `./simulation/run_simulation.sh` |
| **2** | **Universe** | Load Companies, Factors, Clients, and Portfolios into Neo4j. | `./simulation/run_simulation.sh` |
| **3** | **Generation** | Generate synthetic news stories (JSON) via LLM. | `./simulation/run_simulation.sh` |
| **4** | **Ingestion** | Ingest content into Neo4j (Documents) and ChromaDB (Embeddings). | `./simulation/run_simulation.sh` |
| **5** | **Metrics** | Run analytical queries to verify signal propagation. | *Manual / Future Script* |
| **6** | **Review** | Validate final state and artifacts. | `./simulation/validate_simulation.py` |

---

## Prerequisites

Before starting, ensure the production stack is up and Vault is unsealed.

```bash
# 1. Start Infrastructure
./docker/start-prod.sh

# 2. Bootstrap Configuration (if not done)
# This generates config/generated/bootstrap_tokens.json and docker/.env
uv run scripts/bootstrap.py
```

---

## Step-by-Step Execution Guidelines

### Step 0: Clean Slate (Optional but Recommended)

**Goal:** Ensure no lingering data from previous runs affects the current simulation.

```bash
# Wipes Neo4j and ChromaDB data. 
# Requires interactive confirmation unless --force is used.
./simulation/reset_simulation_env.sh
```

### Steps 1-4: The Core Pipeline

The `run_simulation.sh` script is the primary orchestrator. It automatically executes Steps 1 through 4 in sequence and verifies "Stage Gates" after each step.

**Standard Run (Generate 10 stories):**
```bash
# This runs Steps 1, 2, 3, and 4 automatically.
./simulation/run_simulation.sh --count 10
```

**Run using existing data (Skip Generation):**
If you already have valid JSON files in `simulation/test_output` and want to re-ingest them:
```bash
./simulation/run_simulation.sh --skip-generate
```

**What happens inside `run_simulation.sh`:**
1.  **Pre-flight Checks:** Verifies Vault, Neo4j, and ChromaDB are reachable.
2.  **Step 1 (Foundation):** Ensures auth groups/tokens exist and sources are registered. -> **Gate: Auth & Sources**
3.  **Step 2 (Universe):** Loads Companies, Clients, and Portfolios. -> **Gate: Universe & Clients**
4.  **Step 3 (Generation):** Calls LLM to generate news stories. -> **Gate: Generation**
5.  **Step 4 (Ingestion):** Ingests stories via MCP tools. -> **Gate: Ingestion**

### Step 6: Review & Remediation

**Goal:** Perform a final, deep validation of the simulation state.

The orchestrator runs basic gate checks automatically. For detailed inspection, use the standalone validation tool.

```bash
# Run full validation suite (Neo4j counts, ChromaDB embeddings)
uv run python simulation/validate_simulation.py --verbose

# Check a specific gate manually
uv run python simulation/validate_simulation.py --gate ingestion
```

---

## Common Scenarios & Commands

| Scenario | Command |
| :--- | :--- |
| **Full fresh run (10 stories)** | `./simulation/reset_simulation_env.sh --force && ./simulation/run_simulation.sh --count 10` |
| **Debug Ingestion only** | `./simulation/reset_simulation_env.sh --force && ./simulation/run_simulation.sh --skip-generate` |
| **Load Universe only** | `./simulation/run_simulation.sh --init-tokens-only && uv run python -m simulation.load_simulation_data` |
| **Check Health** | `uv run python simulation/validate_simulation.py --verbose` |

## Troubleshooting

*   **"Gate authentication/sources failed":** Ensure `scripts/bootstrap.py` was run and Vault is unsealed.
*   **"Gate ingestion failed":** Check `simulation/ingest_synthetic_stories.py` output. Note that duplicates are skipped, which may affect final counts against expected generation.
*   **"Connection refused":** Ensure you are running commands from the Dev Container or that ports are exposed on localhost. The scripts automatically detect the environment.
