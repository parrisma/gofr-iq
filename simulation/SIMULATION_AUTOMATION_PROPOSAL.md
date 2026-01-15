# Simulation Automation Proposal

**Goal:** Fully automate the `simulation` workflow to run against a fresh production environment, ensuring all necessary groups, tokens, and data are created programmatically without human intervention.

## 1. Problem Statement
Currently, `generate_synthetic_stories.py` and `ingest_synthetic_stories.py` rely on:
1.  Manual creation of `.env.synthetic`.
2.  Pre-existing groups (`apac_sales`, `us_sales`) which don't exist in a fresh `reset-prod` environment.
3.  Pre-existing tokens which expire or are lost on reset.
4.  Manual execution of multiple scripts.

We need a "simulation bootstrapper" that:
*   Links to the **real** production secrets (`docker/.vault-init.env`, `docker/.env`).
*   **Creates** the required groups (`apac_sales`, `us_sales`) using `bootstrap.py` logic or `auth_manager.sh`.
*   **Generates** long-lived tokens for these groups.
*   **Populates** `.env.synthetic` dynamically with these valid tokens.
*   Runs the generation and ingestion pipeline.

## 2. Proposed Architecture

We will create a single Python entrypoint: `simulation/run_simulation.py` (keeps orchestration in one place, no shell parsing).

### 2.1 Workflow Steps
1.  **Environment Check**: Verify `docker/.vault-init.env` exists (Prod is running and bootstrap has emitted admin/public/root tokens). If available, also read `lib/gofr-common/config/gofr_ports.env` to align with the actual Vault port.
2.  **Infrastructure Setup** (The "Bridge"):
    *   Source `docker/.vault-init.env` to get `VAULT_ROOT_TOKEN` (or a non-root admin token if we want to avoid using root) and `GOFR_JWT_SECRET`.
    *   Use Python (AuthService + Vault stores) to:
        *   Create Group: `apac_sales`
        *   Create Group: `us_sales`
        *   Create Token: `apac_sales_token` (Groups: `apac_sales`)
        *   Create Token: `us_sales_token` (Groups: `us_sales`)
        *   Create admin/public tokens for orchestration convenience.
    *   Register sources required by the simulation (e.g., Bloomberg, Reuters) via `scripts/manage_source.sh` before ingestion so document ingestion succeeds on a fresh stack.
3.  **Config Generation**:
    *   Generate `simulation/.env.synthetic` on the fly.
    *   Inject the newly created tokens + Admin/Public tokens (or via new token creation to be safe).
4.  **Data Generation**:
    *   Call `SyntheticGenerator` from Python (no shell) with the generated `.env.synthetic`.
5.  **Data Ingestion**:
    *   Call the ingestion helpers from Python (no shell) reading the same `.env.synthetic`.

### 2.2 Key Components

#### A. `simulation/setup_sim_auth.py` (New Script)
Instead of fragile bash parsing, we will write a Python script that imports `gofr_common` directly (just like `bootstrap.py`) to handle the Auth setup.

*   **Inputs**: `VAULT_ADDR`, `VAULT_TOKEN` (from env). Prefer pulling `VAULT_ADDR` from `gofr_ports.env` or an explicit env var rather than hardcoding (the default Vault port is often 8200; our dev compose may map to 8201).
*   **Actions**:
    *   Connect to Vault.
    *   Initialize `AuthService`.
    *   Ensure groups `apac_sales` and `us_sales` exist (keep scope tight to simulation needs).
    *   Generate 1-year tokens for each plus admin/public for orchestration.
    *   Write `simulation/.env.synthetic` with the format:
        ```env
        GOFR_SYNTHETIC_TOKENS={"admin": "...", "public": "...", "apac_sales": "...", ...}
        # Copy OpenRouter key if available
        GOFR_IQ_OPENROUTER_API_KEY=... 
        ```

#### B. `simulation/run_simulation.py` (Master Script)
```bash
uv run simulation/run_simulation.py --count 10 --output simulation/test_output
# Reuse existing synthetic files instead of regenerating
uv run simulation/run_simulation.py --skip-generate --output simulation/test_output
# Provide a temp API key file (gitignored) or inline key
uv run simulation/run_simulation.py --openrouter-key-file simulation/.env.openrouter
uv run simulation/run_simulation.py --openrouter-key "<temp-key>"
# Run against docker network (Vault at gofr-vault)
uv run simulation/run_simulation.py --docker --skip-generate --output simulation/test_output
```
The script loads secrets, creates groups/tokens, writes `.env.synthetic`, registers sources if missing, generates stories, and ingests them. No shell parsing; all logic in Python.

## 3. Detailed Changes Required

### Phase 1: Authentication Bridge
*   **Create `simulation/setup_sim_auth.py`**:
    *   Adapt logic from `scripts/bootstrap.py`.
    *   Instead of just `admin` and `public` groups, create the simulation-specific groups.
    *   Output the JSON map of `group -> token` to `.env.synthetic`.

### Phase 2: Refactor Generators
*   **Update `generate_synthetic_stories.py`**:
    *   Ensure it respects the `GOFR_SYNTHETIC_TOKENS` map strictly.
    *   Remove any hardcoded fallback tokens (fail fast if env missing).

### Phase 2b: Source Registration
*   **Add an explicit source registration step** (or make ingestion fail fast with a clear error) so a fresh stack has the expected sources before documents are ingested.

### Phase 3: Single Orchestrator
*   **Create `run_simulation.py`** to own env load, group/token provisioning, source registration, generation, and ingestion in-process (invoked via `uv run`).

### Phase 3: Integration
*   Test that `ingest_synthetic_stories.py` effectively uses the tokens created in Phase 1 to ingest into the specific groups.
*   Verify via `manage_document.sh query` that `apac_sales` documents are **NOT** visible to `us_sales` tokens (Group enforcement verification).

## 4. Security Considerations
*   `.env.synthetic` contains valid live tokens. It must be added to `.gitignore`.
*   The script should check if it's running against PROD vs TEST infrastructure to avoid polluting real production data if that distinction matters (likely controlled by `VAULT_ADDR`).

## 5. Success Criteria
*   User runs `./simulation/run_simulation.sh`.
*   Script detects clean prod env.
*   Script provisions `apac_sales` group.
*   Script generates 50 stories.
*   Script ingests 50 stories.
*   User can query stories using the generated tokens.
