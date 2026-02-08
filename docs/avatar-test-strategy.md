# Avatar Feed Simulation - Test Strategy (Sales Trading Focus)

> **Status (2026-02-07):** [PASS] **Tier 1 Deterministic Tests PASSING**
> 
> Last run: `./simulation/run_avatar_simulation.sh --test-set --openrouter-key <KEY>`
> ```
> Summary: 5/5 Passed
> [SUCCESS]  AVATAR FEED UAT: ALL TESTS PASSED
> ```

## 1. Purpose (Business Goal)
The avatar feed exists to **match clients to actionable, client-relevant intelligence** that helps a sales trader prioritize outreach and deliver timely, differentiated ideas. The test strategy must validate that:

1. **Relevance**: Items shown are materially relevant to a client's positions, watchlist, or mandate.
2. **Coverage**: Relevant events are **not missed** when they exist in the graph.
3. **Signal Quality**: Low-impact noise is filtered; high-impact items are ranked higher.
4. **Actionability**: Feeds provide clear "why this matters" reasons aligned to a sales-trading workflow.

We define tests as: **Given test data <X>, expect result <E>, observe actual <A>, and assert pass/fail**.

---

## 2. Controlled Test Data (Clean Start)
**Hard principle:** Every test run **must** start from a clean base by running:

1. `./scripts/start-prod.sh --reset --openrouter-key <KEY>`
2. Graph bootstrap runs automatically as part of start-prod.sh

This is mandatory for determinism, reproducibility, and to avoid stale graph artifacts.

> **IMPORTANT (2026-02-07):** The `start-prod.sh` script now auto-syncs Vault secrets to `docker/.env`.
> This fixed a critical bug where Neo4j passwords would desync after reset. External scripts
> that `source docker/.env` will now get the correct password. See commit for details.

We require deterministic data, not random generation, so we can assert expected outcomes with confidence.

### 2.1 Universe & Tickers
The 16-ticker universe is defined in [simulation/universe/builder.py](simulation/universe/builder.py). We will focus on tickers that cover the sales-trading use cases:

| Ticker | Use Case | Expected Client Exposure |
|--------|----------|--------------------------|
| TRUCK | cyclical, labor/supply chain | Nebula, Ironclad, Green (watchlist) |
| QNTM | high-beta tech | Quantum, Sunrise, DiamondHands (watchlist) |
| ECO | ESG / policy | Green, Nebula (watchlist), Sunrise (watchlist) |
| BANKO | rates / macro | Quantum, Ironclad |
| GENE | unheld control | none (should not surface in Maintenance) |

### 2.2 Client Archetypes (Test Subjects)
Clients are defined in [simulation/generate_synthetic_clients.py](simulation/generate_synthetic_clients.py). For testing, we fix **impact_threshold** to **20-40** so simulated scores (typically 30-80) can pass.

| Client | Holdings (H) | Watchlist (W) | Threshold | Sales-Trading Relevance |
|--------|---------------|---------------|-----------|--------------------------|
| Quantum | QNTM, BANKO | NXS, FIN | 40 | fast-moving tech + rates |
| Nebula | TRUCK, OMNI | ECO, STR | 20 | stable macro + cyclicals |
| Green | ECO, STR | OMNI, TRUCK | 30 | ESG / sustainability |
| Ironclad | BANKO, TRUCK | FIN, STR | 30 | downside + credit stress |

---

## 3. Test Matrix (<E> given <X>)
Each test case defines a **deterministic document** and explicit expected feed behavior.

Test data file: [`simulation/test_data/avatar_test_set.json`](../simulation/test_data/avatar_test_set.json)

### Case 1 - Maintenance Match (Positions)
**Input <X>**: `doc-test-01-truck-strike` "Heavy Truck Strike"
- AFFECTS: TRUCK
- Impact: 60 (SILVER)
- Themes: labor_strike, supply_chain

**Expected <E>**:
- Nebula: MAINTENANCE [PASS] (Holds TRUCK)
- Ironclad: MAINTENANCE [PASS] (Shorts TRUCK)
- Green: MAINTENANCE [PASS] (Watchlist TRUCK)
- Quantum: [FAIL] (no exposure)

### Case 2 - Opportunity Match (Mandate/ESG)
**Input <X>**: `doc-test-02-eco-subsidy` "Green Energy Bill"
- AFFECTS: ECO
- Impact: 85 (GOLD)
- Themes: clean_energy, policy

**Expected <E>**:
- Green: MAINTENANCE [PASS] (Holds ECO) - maintenance wins over opportunity
- Nebula: MAINTENANCE [PASS] (Watchlist ECO)
- Quantum: [FAIL] (no exposure to ECO)

### Case 3 - Tech Breakthrough (NXS)
**Input <X>**: `doc-test-03-nxs-ai-breakthrough` "Quantum AI Model"
- AFFECTS: NXS
- Impact: 95 (PLATINUM)
- Themes: ai_hardware, innovation

**Expected <E>**:
- Quantum: MAINTENANCE [PASS] (Watchlist NXS)
- Other clients with NXS exposure should see it

### Case 4 - Threshold Filter
**Input <X>**: `doc-test-05-banko-earnings` "BankOne Steady Earnings"
- AFFECTS: BANKO
- Impact: 25 (STANDARD)

**Expected <E>**:
- Quantum: [FAIL] filtered (threshold 40, score 25)
- Ironclad: [FAIL] filtered (threshold 30, score 25)

### Case 5 - False Positive Guard (Control)
**Input <X>**: `doc-test-04-gene-trial-fail` "GeneSys Trial Fails"
- AFFECTS: GENE
- Impact: 40 (BRONZE)

**Expected <E>**:
- No client should see it in MAINTENANCE (no holdings/watchlist exposure to GENE)
- Only clients with matching mandate themes (if any) should see it in OPPORTUNITY

---

## 4. Required Support Scripts (for <X>, <E>, <A>)
We need reliable scripts to query Neo4j and Chroma to confirm actual data before assertions.

### 4.1 Graph Probe (Neo4j)
**Implemented**: `simulation/scripts/probe_graph.py`

```bash
# Check client profile (holdings, watchlist, threshold, themes)
uv run simulation/scripts/probe_graph.py --client "Nebula"

# Check ticker and connected documents
uv run simulation/scripts/probe_graph.py --ticker "TRUCK"

# Check document relationships
uv run simulation/scripts/probe_graph.py --doc "doc-test-01"
```

**Output fields**: name, guid, impact_threshold, mandate_themes, holdings, watchlist

### 4.2 Embedding Probe (Chroma)
**Implemented**: `simulation/scripts/probe_chroma.py`

```bash
# Check document exists in vector store
uv run simulation/scripts/probe_chroma.py --document "doc-test-01"

# Run similarity search
uv run simulation/scripts/probe_chroma.py --query "truck strike" --limit 5

# Show collection statistics
uv run simulation/scripts/probe_chroma.py --stats
```

**Output fields**: document_guid, title, impact_score, impact_tier, source_guid, content snippet

> Note: For avatar feed testing, Chroma is less critical since the feed logic uses
> graph traversal (AFFECTS relationships) rather than vector similarity.

These probes create a **systematic bridge** between <X> and <A>.

---

## 5. Enhancements to run_avatar_simulation.sh
The script should **drive the test suite**, not require manual debugging.

### Implemented flags [PASS]
- `--test-set`: ingest deterministic JSON set from `simulation/test_data/avatar_test_set.json`
- `--skip-reset`: skip the reset step (for faster iteration)
- `--skip-ingest`: skip document generation/ingestion
- `--openrouter-key KEY`: pass API key for automated runs

### Future flags (not yet implemented)
- `--seed N`: seed deterministic random generation
- `--expectations PATH`: JSON of expected results per client
- `--report-json PATH`: machine-readable results
- `--report-md PATH`: human summary
- `--require-nonempty`: fail if any client feed is empty
- `--min-pass-rate 0.95`: enforce minimum coverage

### Recommended workflow
1. Reset prod stack
2. Load deterministic test set
3. Run validation with expectation comparison
4. Emit structured report with metrics

---

## 6. Test Strategy Ladder (Increasing Complexity)
We build from **simple correctness** to **realistic market stress**:

1. **Tier 0 - Smoke**: schema + connectivity (MCP, Neo4j, Chroma).
2. **Tier 1 - Deterministic**: 5-8 fixed documents with golden expectations.
3. **Tier 2 - Semi-random**: seeded generation with constraints (guaranteed tickers present).
4. **Tier 3 - Stress**: 200+ docs, multiple overlapping themes, ranking quality checks.
5. **Tier 4 - Regression**: compare KPIs vs last successful run.

---

## 7. Report Requirements (Quantified Results)
The final report must **quantify signal quality** for sales trading:

### Per-Client KPIs
- **Coverage**: % of expected docs surfaced
- **Precision Proxy**: % of feed items with valid exposure or theme match
- **Empty Feed Rate**: should be 0% for deterministic test set
- **Ranking Quality**: top-3 items include at least one expected high-impact event
- **Latency** (optional): time from ingest to feed availability

### Example Report
```
Avatar Feed Test Report
=======================
Client: Nebula Retirement Fund
  Coverage: 3/3 (100%)
  Precision: 6/6 (100%)
  Top-3 contains TRUCK strike [PASS]

Client: Quantum Momentum Partners
  Coverage: 1/2 (50%) [FAIL]
  Missing: Banko surprise guidance (expected)
  Root cause: impact_score below threshold
```

---

## 8. Acceptance Criteria
We consider the avatar feed test suite successful when:

1. Deterministic tests pass **100%** on a clean start.
2. Semi-random tests pass **>= 95%** coverage and **>= 90%** precision proxy.
3. No client in deterministic suite has an empty feed.
4. Any failure emits a **structured root-cause** entry (data missing, filter mismatch, or theme mismatch).

---

## 9. Step-by-Step Implementation Plan (Checklist)

### Phase 0 - Clean Start Foundation (MANDATORY)
- [x] Document the hard requirement in all test scripts: `./scripts/start-prod.sh --reset` then bootstrap.
- [x] **Fixed (2026-02-07)**: Password sync issue - `start-prod.sh` now writes Vault secrets to `docker/.env`.
- [x] Bootstrap graph runs automatically as part of `start-prod.sh --reset`.
- [x] Add a guard in `run_avatar_simulation.sh` that refuses to proceed unless reset+bootstrap were executed in the same run (or a `--force` override with warning).

### Phase 1 - Deterministic Test Data
- [x] Create `simulation/test_data/avatar_test_set.json` with 5 fixed documents covering Cases 1-4.
- [x] Ensure each document specifies: title, content, source_guid, ticker mentions, themes, impact_score/tier.
- [x] Add deterministic mapping in JSON (`simulated_impact.affects` per document).

### Phase 2 - Support Probes
- [x] Implement `simulation/scripts/probe_graph.py` for client and ticker inspection.
- [x] Implement `simulation/scripts/inject_test_data.py` for deterministic graph injection.
- [x] Implement `simulation/scripts/validate_test_set.py` for golden set validation.
- [x] Implement `simulation/scripts/probe_chroma.py` for document vector presence and metadata.
- [x] Update docs with example commands and expected output fields.

### Phase 3 - Runner Enhancements
- [x] Add `--test-set` flag to `run_avatar_simulation.sh` (uses `simulation/test_data/avatar_test_set.json`).
- [x] Add `--openrouter-key KEY` for non-interactive runs.
- [x] Add `--skip-reset` and `--skip-ingest` for faster iteration.
- [x] Add `--expectations PATH` to load expected results from external JSON.
- [x] Add `--report-json PATH` and `--report-md PATH` outputs.
- [x] Add `--require-nonempty` and `--min-pass-rate` enforcement flags.

### Phase 4 - Validator Enhancements
- [x] Extend `validate_test_set.py` to support expectations, report outputs, and enforcement flags.
- [x] Emit structured failure reasons (missing doc, wrong channel, filtered by threshold, theme mismatch).
- [x] Include per-client KPIs (coverage, precision proxy, ranking quality).

### Phase 5 - Regression Workflow
- [x] Add `simulation/scripts/golden_baseline.py save` command to save JSON expectations from a known-good state.
- [x] Add `simulation/scripts/golden_baseline.py diff` command to compare current run vs last golden run.
- [ ] Require Tier-1 deterministic tests to pass before Tier-2+.
