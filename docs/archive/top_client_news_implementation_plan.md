# Implementation Plan: Top Client News Alpha Engine

**Date**: 2026-02-21
**Specs**: [docs/top_client_news_logic_spec.md](docs/top_client_news_logic_spec.md)
**Goal**: Transform `get_top_client_news` from a static retrieval into a dynamic "Alpha Engine" maximizing relevance and utility.

## Progress (as of 2026-02-21)

**Implemented:** M0 through M6 (Phase 1 + Phase 2) are complete and the full test suite is green.

**How to run tests:**
*   Targeted gate (M0): `./scripts/run_tests.sh -k "duplicate or alias"`
*   Full suite (deterministic): `./scripts/run_tests.sh`
*   Full suite including live LLM integration/e2e tests (opt-in):
        *   `GOFR_IQ_RUN_LLM_INTEGRATION_TESTS=1 ./scripts/run_tests.sh --api-key <openrouter-key>`

**Remaining:** Phase 3 (simulation validation scenarios + bias sweep) is in progress; Phase 4 (tuning/calibration) is pending.

## Milestones (Source Control Checkpoints)

Each milestone below should be implemented as a small PR with its own tests and a clear rollback surface. The goal is that every merge leaves the system runnable and measurable.

**Global gates (apply to every milestone):**
*   Run `./scripts/run_tests.sh` (targeted tests first, full suite at least once per phase).
*   No new logging patterns: use `StructuredLogger` only.
*   Prefer additive changes (new schema elements, new properties) over breaking migrations.

**M0: Baseline + Guardrails**
*   Deliverables: small unit tests for duplicate detection + alias resolution (even before wiring into ingestion), and a short doc note in this plan describing how to run the targeted checks.
*   Exit criteria: `./scripts/run_tests.sh -k "duplicate or alias"` is green.

**M0 targeted checks**
*   Run: `./scripts/run_tests.sh -k "duplicate or alias"`
*   Tests covered today: `test/test_duplicate_detection.py` and `test/test_alias_resolution.py`

**M1: Client Profile App Model (schema + adapters)**
*   Deliverables: `app/models/client_profile.py` (Pydantic), plus adapter code so `QueryService` can parse Neo4j profile properties without changing query semantics.
*   Exit criteria: no behavior change in `get_top_client_news`; tests green.

**M2: Alias Node Pattern (schema + resolver + seed loader)**
*   Deliverables: Neo4j schema updates (Alias node + constraints), `AliasResolver`, ingestion hook for instruments, and `scripts/load_aliases.py`.
*   Exit criteria: ingest a story that uses a name variant/alternate identifier and confirm it links to the canonical instrument; tests green.

**M3: Duplicate Detection Hardening (semantic + structural + persistence)**
*   Deliverables: persisted hash/fingerprint fields (Neo4j + Document metadata), Chroma-based near-duplicate query within a time window, and deterministic structural fingerprinting.
*   Exit criteria: three-wire paraphrase test dedupes; cross-quarter earnings test does not falsely dedupe.

**M4: Mandate Enrichment + Embeddings (themes + vector)**
*   Deliverables: mandate theme extraction stored as `mandate_themes`, mandate embedding generation/backfill, and retrieval path that can fetch the embedding quickly.
*   Exit criteria: at least one client has `mandate_themes`; embeddings exist for a sample set; tests green.

**M5: `get_top_client_news` Interface Upgrade (bias parameter + config)**
*   Deliverables: `opportunity_bias` plumbing, `ScoringConfig`, and unit tests for lambda boundary behavior ($\lambda=0, 0.5, 1$).
*   Exit criteria: API backward compatible (default behavior matches current output ordering for a fixed fixture).

**M6: Hybrid Retrieval + Scoring (Graph + Vector)**
*   Deliverables: vector candidate generation via mandate embedding, merge/dedupe strategy, and scoring equation implementation (including boosts).
*   Exit criteria: simulation scenarios pass; bias sweep shows monotonic behavior (thematic items rise as $\lambda$ increases).

## Phase 1: Foundations & Data Enrichment
*Status: Completed*

**Objective**: Ensure the data graph has the necessary semantic pathways (Themes, Embeddings, Event Types) before we change the retrieval logic.

1.  **Refactor Client Profile Model**
        *   [x] Promote `ClientProfile` from a simulation artifact to a first-class Pydantic model in `app/models/client_profile.py`.
        *   [x] Add `mandate_text`, `mandate_themes: list[str]`, `mandate_embedding: list[float]` fields.
                *   [x] Update `QueryService` to use this model instead of raw dicts.
        *   Milestone: M1

2.  **Enrich Client Mandates (Thematic Extraction)**
        *   [x] Update mandate enrichment to extract themes into `ClientProfile.mandate_themes`.
        *   [x] Add `ClientProfile.mandate_embedding` (vector) to the schema and persist it.
        *   [x] Batch/backfill existing clients to populate these fields.
        *   *Test*: Verify `MATCH (c:ClientProfile) WHERE c.mandate_themes IS NOT NULL RETURN count(c)` > 0.
        *   *Test*: Verify embeddings are stored in ChromaDB (optional, or just graph properties).
        *   Milestone: M4

3.  **Enrich Documents (Thematic & Event Tagging)**
        *   [x] Verify `IngestService` tags documents with `VALID_THEMES`.
        *   [x] Verify `IngestService` maps `event_type` correctly (e.g., "M_AND_A", "EARNINGS").
        *   [x] Ensure Documents have vector embeddings stored in ChromaDB upon ingestion.
        *   *Test*: Verify `MATCH (d:Document) WHERE d.themes IS NOT NULL RETURN count(d)` > 0.
        *   Milestone: M4 (prerequisite for hybrid retrieval)

4.  **Entity Alias Resolution (Instruments & Clients)**
    *   [x] **Schema**: Add `Alias` node type to `graph_index.py init_schema()` with
            properties `value`, `scheme`, `canonical_guid`. Add `HAS_ALIAS` relationship
            type. Add uniqueness constraint on `(scheme, value)`.
            `scheme` values: `TICKER | RIC | SEDOL | ISIN | CUSIP | FIGI | NAME_VARIANT`
            (instruments) or `SFDC | BBG_FIRM | LEGAL_NAME | DESK_ALIAS` (clients).
    *   [x] **`AliasResolver` service** (~150 lines): `resolve(value, scheme=None) -> canonical_guid`.
            Cypher: `MATCH (a:Alias {value: $v})-[:HAS_ALIAS]-(target) RETURN target.guid`.
            LRU cache to avoid hitting Neo4j on every ingest call.
    *   [x] **Ingestion hook**: In `IngestService._index_instruments`, before calling
            `create_instrument`, run extracted company names / tickers through
            `AliasResolver.resolve()`. If it matches a canonical node, reuse it instead of
            creating a duplicate. Log unresolved aliases for review.
    *   [x] **Bulk seed script**: CSV/JSON loader (`scripts/load_aliases.py`) to import
            reference data (Bloomberg export, Salesforce dump, ticker->name variant mappings).
    *   *Test*: Ingest a story referencing "Alphabet" and verify it resolves to the `GOOGL`
            Instrument node via alias lookup.
        *   Milestone: M2

5.  **Harden Duplicate Detection (`DuplicateDetector`)**

    **Current state weaknesses:**
    - In-memory only: hash + similarity indexes lost on restart. `load_documents()`
      requires O(N) scan of all stored docs to rebuild.
    - O(N) brute-force similarity scan against every registered document on each ingest.
    - Bag-of-words cosine (term frequency) -- misses paraphrased duplicates (same event,
      different wording from Reuters vs Bloomberg vs AP).
    - No cross-language detection (English AAPL story vs Japanese AAPL story).
    - Threshold 0.95 is too high: multi-source coverage of the same event typically scores
      0.70-0.90 on bag-of-words cosine. Real duplicates a trader cares about slip through.
    - ChromaDB vector embeddings already exist for every document but are not used.
    - No temporal windowing: checks against all history, risking false positives across
      quarters (e.g., this quarter's AAPL earnings vs last quarter's).
    - `group` parameter accepted but unused.

    **Proposed improvements:**
    *   [x] **Use ChromaDB for near-duplicate detection**: At ingest, query ChromaDB
            for documents with cosine similarity > 0.85 within a 48-hour window. This
            replaces the O(N) in-memory scan with ChromaDB's optimised ANN index and
            catches semantic paraphrases the bag-of-words approach misses.
    *   [x] **Lower similarity threshold to 0.85**: Calibrated to catch multi-source
            wire rewrites while avoiding false positives on recurring events.
    *   [x] **Add entity+event fingerprint**: After extraction, compute a "story fingerprint"
            from `(sorted affected_tickers, event_type, date)`. Two documents with the same
            fingerprint within 24 hours are near-certain duplicates regardless of wording.
            Fast O(1) lookup in a dict/Neo4j index without any vector math.
    *   [x] **Temporal windowing**: Only compare against documents from the last 48 hours,
            not all history. Eliminates cross-quarter false positives.
    *   [x] **Persist hash index to Neo4j**: Store `content_hash` as a property on the
            Document node with a Neo4j index. On startup, no need to reload all documents
            into memory -- the hash check becomes a Cypher lookup.
    *   [x] **Cross-language dedup via embeddings**: Documents are embedded in a
            language-agnostic model. ChromaDB similarity already handles this if we use it.
    *   *Test*: Ingest the same AAPL earnings story from 3 different sources with different
            wording. Verify only the first is scored; the other two are flagged as duplicates.
    *   *Test*: Ingest an AAPL earnings story this quarter and last quarter. Verify they are
            NOT flagged as duplicates despite high term overlap.
        *   Milestone: M3

## Phase 2: Core Algorithm Upgrade (The Engine)
*Status: Completed*

**Objective**: Rewrite `QueryService.get_top_client_news` to implement the Hybrid Scoring/Bias Logic.

6.  **Refactor Signature & Interface**
        *   [x] Update `get_top_client_news` to accept `opportunity_bias: float = 0.0`.
        *   [x] Create `ScoringConfig` dataclass to hold the dynamic weights (derived from $\lambda$) and replace/extend `ClientNewsWeights`.
        *   Milestone: M5

7.  **Implement Hybrid Retrieval (Graph + Vector)**
        *   [x] **Graph Query**: Enhance existing `_get_documents_for_tickers` to support path counting (influence boost).
        *   [x] **Vector Query**: Implement `_get_documents_by_vector(mandate_embedding)` using `EmbeddingIndex` when $\lambda > 0.5$.
        *   [x] **Merge Strategy**: Union results by `document_guid` and track source (`graph` vs `vector`).
        *   Milestone: M6

8.  **Implement Dynamic Scoring Strategy**
        *   [x] Code the $\lambda$ formulas for Base Score (Holdings vs. Thematic).
        *   [x] Code the **Exponential Recency** decay ($t_{1/2} = 60m$).
        *   [x] Code the **Non-Linear Position Boost** (Logarithmic).
        *   [x] Code the **Influence Boost** (Path counting).
        *   Milestone: M6

## Phase 3: Validating with Simulation (Sunshine & Rain)
*Status: Completed*

**Objective**: Prove the algo works by generating stress-test scenarios where "Old Algo" fails and "New Algo" succeeds.

9.  **Upgrade Synthetic Story Generator (`generate_synthetic_stories.py`)**
        *   [x] **Scenario A (Defense)**: "Massive failure in a 0.5% tail holding." (Should likely be ignored/low-ranked unless $\lambda=0.0$).
        *   [x] **Scenario B (Offense)**: "Competitor M&A in a sector matching Client Mandate." (Should be #1 rank when $\lambda=1.0$).
        *   [x] **Scenario C (Systemic)**: "Supplier explosion affecting 3 holdings." (Should bubble up via Influence boost).
        *   [x] **Scenario D (Noise)**: "Generic sector noise." (Should be suppressed).
        *   [x] Add deterministic generation mode: `uv run python simulation/generate_synthetic_stories.py --mode generate --phase3 --output simulation/test_output`
        *   [x] Add end-to-end runner flag: `./simulation/run_simulation.sh --phase3 --regenerate`

10. **Refine Avatar Simulation (`validate_avatar_feeds.py`)**
        *   [x] Add `bias_sweep` mode: Run validation at $\lambda=[0.0, 0.5, 1.0]$.
        *   [x] **Metric: Recall@3**: How often is the *intended* stress-test story found in the Top 3?
        *   [x] **Metric: Alpha Score**: (Custom metric measuring relevance of non-holdings).
        *   [x] Command: `uv run python simulation/validate_avatar_feeds.py --bias-sweep --lambdas 0,0.5,1`

**Phase 3 measured results (latest run):**
*   Bias sweep (Recall@3) for scenarios A/B/C (noise scenario D excluded):
                *   $\lambda=0.0$: Recall@3 = 1.000 (3/3)
                *   $\lambda=0.5$: Recall@3 = 1.000 (3/3)
                *   $\lambda=1.0$: Recall@3 = 1.000 (3/3)

## Phase 4: Tuning & Calibration (The "Sales Trader" Loop)
*Status: In Progress*

**Objective**: Determine the optimal default weights using quantitative feedback.

**Core idea**: Phase 4 is not "generate 500 and hope". We will:
1) create a large, noisy document pool (realistic competition),
2) inject deterministic calibration stories targeting all 6 client mandates, with encoded expectations,
3) run the avatar simulation as the measurement harness to confirm client-specific ranking, relationship handling, and negative-control suppression across $\lambda$.

**Simulation capabilities (implemented):**
*   `CLIENT_PORTFOLIOS` and `CLIENT_WATCHLISTS` cover all 6 stable clients (GUIDs `...0001` through `...0006`), matching `simulation/generate_synthetic_clients.py`.
*   28 total scenarios (17 random-pool + 4 Phase3 + 11 Phase4). Phase4 scenarios have `weight=0.0` so they are never randomly selected.
*   Phase4 calibration set (11 scenarios in 3 groups):
    *   **Group A -- Mandate needles (M1-M6)**: one per client archetype, non-holding thematic stories targeting AI/semiconductor, commodities/rates, blockchain, ESG/energy-transition, cloud/consumer, and credit/geopolitical mandates.
    *   **Group B -- Relationship hops (R1-R3)**: 1-hop supplier disruption (ECO->VELO), 2-hop competitor recall (GENE->VIT), and systemic multi-ticker shock (OMNI+SHOPM+TRUCK).
    *   **Group C -- Negative controls (N1-N2)**: generic sector noise and wrong-theme strong headline (should NOT rank in Top 3 for any client).
*   Each Phase4 case has deterministic title (`[Phase4 <name>] TICKER - Name`), forced ticker selection, and recent timestamps (within 1h).
*   Harness reports per-group metrics: Phase3 Recall@3, Phase4 Recall@3, mandate needles, relationship hops, negative-control suppression rate, and AlphaScore.

11. **Run Large-Scale Simulation**
    *   [ ] Generate + ingest a large background corpus (the "market noise" / competition set):
            *   Command: `./simulation/run_simulation.sh --count 500 --regenerate`.
            *   Purpose: create enough competing documents so the ranking function is forced to make trade-offs (holdings vs thematic vs recency vs influence).
    *   [ ] Inject Phase3 calibration cases:
            *   Command: `./simulation/run_simulation.sh --phase3 --regenerate`.
            *   What gets injected (Phase 3 A/B/C; D is noise and is intentionally excluded from Recall@3 evaluation):
                    *   **Phase3 A (Defense / tail holding failure)**: expected client `...0001`.
                    *   **Phase3 B (Offense / thematic M&A, non-holding)**: expected to rise as $\lambda$ increases; expected client `...0003`.
                    *   **Phase3 C (Systemic / multi-holding shock)**: exercises influence/path logic; expected client `...0001`.
    *   [ ] Inject Phase4 calibration cases:
            *   Command: `./simulation/run_simulation.sh --phase4 --regenerate`.
            *   What gets injected (11 scenarios):
                    *   **M1 AI Compute Supply Chain** (GENE): expected client `...0001` (Quantum Momentum Partners, ai/semiconductor mandate).
                    *   **M2 Rates Shock Inflation Print** (PROP): expected client `...0002` (Nebula Retirement Fund, commodities/rates mandate).
                    *   **M3 Crypto Protocol Exploit** (FIN): expected client `...0003` (DiamondHands420, blockchain/ev_battery mandate).
                    *   **M4 Energy Transition Policy** (VELO): expected client `...0004` (Green Horizon Capital, esg/energy_transition mandate).
                    *   **M5 Cloud Pricing SaaS Shift** (LUXE): expected client `...0005` (Sunrise Long Opportunities, cloud/consumer mandate).
                    *   **M6 Credit Downgrade Geopolitical** (VIT): expected client `...0006` (Ironclad Short Strategies, credit/geopolitical mandate).
                    *   **R1 Supplier Disruption 1Hop** (ECO->VELO): expected client `...0003`; tests 1-hop partner traversal.
                    *   **R2 Competitor Recall 2Hop** (GENE->VIT): expected client `...0001`; tests 2-hop competitor traversal.
                    *   **R3 Systemic Multi-Ticker Shock** (OMNI+SHOPM+TRUCK): expected client `...0002`; tests multi-holding influence boost.
                    *   **N1 Generic Sector Chatter** (PROP): expected clients `[]`; should NOT appear in Top 3 for any client.
                    *   **N2 Wrong Theme Strong Headline** (GENE): expected clients `[]`; false-positive guard.
            *   Why inject AFTER the 500-run: the avatar harness selects the most recent synthetic file per scenario, and stories must be recent enough to be queryable in the time window.
    *   [ ] Inspect `simulation/test_output/` JSONs for injected cases (sanity check):
            *   Confirm each Phase3/Phase4 JSON has:
                    *   `validation_metadata.scenario` starting with `Phase3` or `Phase4`
                    *   deterministic title prefix (used for matching)
                    *   `validation_metadata.expected_relevant_clients`
                    *   `validation_metadata.base_ticker`
    *   [x] Smoke run after full reset: `./simulation/run_simulation.sh --count 20 --regenerate` (all gates passed; 20 uploaded, 0 failed).

12. **Quantify "Bias Sensitivity"**
    *   [ ] Use avatar simulation as the measurement harness (client-specific validation):
            *   Command: `uv run python simulation/validate_avatar_feeds.py --bias-sweep --lambdas 0,0.25,0.5,0.75,1`
            *   What this verifies:
                    *   **Client-specific ranking (all 6 clients)**: each Phase3 and Phase4 case encodes `expected_relevant_clients`; Recall@3 checks the intended story appears in the Top 3 for the intended client(s).
                    *   **Mandate coverage**: Phase4 M1-M6 target each of the 6 client archetypes independently; if mandate embedding or theme matching is broken for a specific archetype, it shows up as a per-client recall gap.
                    *   **Relationship handling under competition**: R1 (1-hop supplier), R2 (2-hop competitor), and R3 (multi-holding systemic) are additional diagnostic needles beyond Phase3 C. If graph traversal or influence boost is broken, these cases stop surfacing for the intended clients.
                    *   **Negative-control suppression**: N1 and N2 should NOT appear in any client's Top 3. The harness reports a suppression rate (target: 1.0).
                    *   **Bias response**: Phase3 B and Phase4 M1-M6 are the primary needles for the thematic/non-holding path; their rank should improve as $\lambda$ increases.
            *   Harness output per $\lambda$:
                    *   Phase3 Recall@3 (A/B/C)
                    *   Phase4 Recall@3 (all non-negative cases)
                    *   Phase4 Mandate needles Recall@3 (M1-M6)
                    *   Phase4 Relationship hops Recall@3 (R1-R3)
                    *   Phase4 Suppression rate (N1-N2)
                    *   AlphaScore (proportion of Top 3 with no holdings overlap)
    *   [ ] Measure crossover point ("sales trader" intuition target): At what $\lambda$ does a strong thematic/non-holding item overtake a mid-strength holding-driven item?
            *   Tooling: `uv run python simulation/measure_bias_sensitivity.py --lambdas 0,0.25,0.5,0.75,1`
            *   Interpretation:
                    *   If ranks are flat across all $\lambda$, either (a) thematic candidates are not entering the candidate set, or (b) $\lambda$ weights are not being applied, or (c) the injected set is too weak relative to holdings-driven items.
                    *   If Phase4 mandate needles show recall for the wrong clients, tighten ticker/theme specificity in prompts or adjust `expected_relevant_clients`.
    *   [ ] Preconditions to make the $\lambda$ sweep meaningful:
            *   Ensure client mandate embeddings exist (vector path only activates when $\lambda>0.5$ AND `mandate_embedding` exists).
            *   Ensure document theme tags are present/queryable (theme-based retrieval participates at all $\lambda$).
            *   Ensure Phase3 + Phase4 cases are recently ingested (the MCP time window is capped; old injected docs silently disappear from the evaluation window).

    **Where the avatar simulation fits**:
    *   Phase 3 used it to prove the algorithm works on a clean, small set (4 scenarios, 1 client archetype).
    *   Phase 4 uses it as the regression harness + tuning dashboard against a large, noisy corpus with all 6 client archetypes, relationship-hop validation, and negative-control suppression.
    *   The avatar harness is the fastest way to answer: "Did we break client-specific ranking or relationship traversal while changing weights?" before paying the cost of repeated 500-run iterations.

    **Suggested Phase 4 workflow:**
    ```
    ./simulation/run_simulation.sh --count 500 --regenerate
    ./simulation/run_simulation.sh --phase3 --regenerate
    ./simulation/run_simulation.sh --phase4 --regenerate
    uv run python simulation/validate_avatar_feeds.py --bias-sweep --lambdas 0,0.25,0.5,0.75,1
    ```

        **Phase 4 measured results (clean env + 20 stories + Phase3 injected; 6h window):**
        *   `Sunrise Long Opportunities`: Scenario B rank improved as $\lambda$ increased (B=6 at $\lambda=0.0$ -> B=2 at $\lambda=1.0$); Scenario C stayed rank 1.
        *   `Quantum Momentum Partners`: Scenario A/B/C ranks shifted slightly at high $\lambda$ (A improved to rank 3; C moved to rank 2 at $\lambda=1.0$).

13. **Final Polish**
    *   [ ] Update `AvatarFeed` to support the new scoring model if needed (or keep separate).
    *   [ ] Update System Prompts to reflect the bias tone ("Warn me" vs "Inspire me").
    *   [ ] Documentation & rollout.

## Future Extensions (Post-Phase 4)

### Index Rebalance & Benchmark Composition Awareness
The current model recognises index events at extraction time (`INDEX_ADD`, `INDEX_DELETE`,
`INDEX_REBAL`) and defines the graph schema (`CONSTITUENT_OF`, `BENCHMARKED_TO`), but the
scoring/query layer has no awareness of benchmark composition or active weight. Key items:

*   [ ] **Populate `CONSTITUENT_OF`**: Bootstrap and maintain Instrument -> Index membership
        in Neo4j so the graph connects index events to affected benchmarks.
*   [ ] **Active Weight Calculation**: Store benchmark weights alongside portfolio weights so
        the system can compute active weight (overweight/underweight). A stock entering a
        client's benchmark at 1.5% while the client holds 0% is a -1.5% active underweight
        that creates immediate tracking error -- a forced-flow event for passive/index-aware
        mandates.
*   [ ] **Benchmark-Aware Scoring**: In `get_top_client_news`, boost `INDEX_ADD`/`INDEX_DELETE`
        events when the affected instrument is a constituent of (or is being added to/removed
        from) the client's benchmark. This should rank near the top for passive and
        benchmark-sensitive clients, not be treated as generic watchlist noise.
*   [ ] **Event-Type Boosting**: Implement the spec Section 2.4C event-type boost (currently
        ignored). `INDEX_ADD`/`INDEX_DELETE` on a benchmark constituent is one of the
        highest-conviction short-term trading signals on the desk.

### Silent Risk Detection ("Dog That Didn't Bark")
*   [ ] Flag expected-but-missing events (e.g., scheduled earnings with no release after +2h)
        as high-priority gaps.

### Cross-Client Alpha Contagion
*   [ ] If a news item scores > 0.9 for many clients sharing a theme, boost it for other
        clients with the same theme but lower initial conviction ("Smart Money is Watching").

