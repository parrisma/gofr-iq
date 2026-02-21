# Implementation Plan: Top Client News Alpha Engine

**Date**: 2026-02-21
**Specs**: [docs/top_client_news_logic_spec.md](docs/top_client_news_logic_spec.md)
**Goal**: Transform `get_top_client_news` from a static retrieval into a dynamic "Alpha Engine" maximizing relevance and utility.

## Milestones (Source Control Checkpoints)

Each milestone below should be implemented as a small PR with its own tests and a clear rollback surface. The goal is that every merge leaves the system runnable and measurable.

**Global gates (apply to every milestone):**
*   Run `./scripts/run_tests.sh` (targeted tests first, full suite at least once per phase).
*   No new logging patterns: use `StructuredLogger` only.
*   Prefer additive changes (new schema elements, new properties) over breaking migrations.

**M0: Baseline + Guardrails**
*   Deliverables: small unit tests for duplicate detection + alias resolution (even before wiring into ingestion), and a short doc note in this plan describing how to run the targeted checks.
*   Exit criteria: `./scripts/run_tests.sh -k "duplicate|alias"` is green.

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
*Status: Ready to Start*

**Objective**: Ensure the data graph has the necessary semantic pathways (Themes, Embeddings, Event Types) before we change the retrieval logic.

1.  **Refactor Client Profile Model**
    *   [ ] Promote `ClientProfile` from a simulation artifact to a first-class Pydantic model in `app/models/client_profile.py`.
    *   [ ] Add `mandate_text`, `mandate_themes: list[str]`, `mandate_embedding: list[float]` fields.
        *   [ ] Update `QueryService` to use this model instead of raw dicts.
        *   Milestone: M1

2.  **Enrich Client Mandates (Thematic Extraction)**
        *   [ ] Update mandate enrichment to extract themes into `ClientProfile.mandate_themes`.
        *   [ ] Add `ClientProfile.mandate_embedding` (vector) to the schema (graph property and/or Chroma collection; choose one canonical path).
    *   [ ] Batch process all existing simulation clients to populate these fields.
        *   *Test*: Verify `MATCH (c:ClientProfile) WHERE c.mandate_themes IS NOT NULL RETURN count(c)` > 0.
    *   *Test*: Verify embeddings are stored in ChromaDB (optional, or just graph properties).
        *   Milestone: M4

3.  **Enrich Documents (Thematic & Event Tagging)**
    *   [ ] Verify `IngestService` tags documents with `VALID_THEMES`.
    *   [ ] Verify `IngestService` maps `event_type` correctly (e.g., "M_AND_A", "EARNINGS").
    *   [ ] Ensure Documents have vector embeddings stored in ChromaDB upon ingestion.
    *   *Test*: Verify `MATCH (d:Document) WHERE d.themes IS NOT NULL RETURN count(d)` > 0.
        *   Milestone: M4 (prerequisite for hybrid retrieval)

4.  **Entity Alias Resolution (Instruments & Clients)**
    *   [ ] **Schema**: Add `Alias` node type to `graph_index.py init_schema()` with
            properties `value`, `scheme`, `canonical_guid`. Add `HAS_ALIAS` relationship
            type. Add uniqueness constraint on `(scheme, value)`.
            `scheme` values: `TICKER | RIC | SEDOL | ISIN | CUSIP | FIGI | NAME_VARIANT`
            (instruments) or `SFDC | BBG_FIRM | LEGAL_NAME | DESK_ALIAS` (clients).
    *   [ ] **`AliasResolver` service** (~150 lines): `resolve(value, scheme=None) -> canonical_guid`.
            Cypher: `MATCH (a:Alias {value: $v})-[:HAS_ALIAS]-(target) RETURN target.guid`.
            LRU cache to avoid hitting Neo4j on every ingest call.
    *   [ ] **Ingestion hook**: In `IngestService._index_instruments`, before calling
            `create_instrument`, run extracted company names / tickers through
            `AliasResolver.resolve()`. If it matches a canonical node, reuse it instead of
            creating a duplicate. Log unresolved aliases for review.
    *   [ ] **Bulk seed script**: CSV/JSON loader (`scripts/load_aliases.py`) to import
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
    *   [ ] **Use ChromaDB for near-duplicate detection**: At ingest, query ChromaDB
            for documents with cosine similarity > 0.85 within a 48-hour window. This
            replaces the O(N) in-memory scan with ChromaDB's optimised ANN index and
            catches semantic paraphrases the bag-of-words approach misses.
    *   [ ] **Lower similarity threshold to 0.85**: Calibrated to catch multi-source
            wire rewrites while avoiding false positives on recurring events.
    *   [ ] **Add entity+event fingerprint**: After extraction, compute a "story fingerprint"
            from `(sorted affected_tickers, event_type, date)`. Two documents with the same
            fingerprint within 24 hours are near-certain duplicates regardless of wording.
            Fast O(1) lookup in a dict/Neo4j index without any vector math.
    *   [ ] **Temporal windowing**: Only compare against documents from the last 48 hours,
            not all history. Eliminates cross-quarter false positives.
    *   [ ] **Persist hash index to Neo4j**: Store `content_hash` as a property on the
            Document node with a Neo4j index. On startup, no need to reload all documents
            into memory -- the hash check becomes a Cypher lookup.
    *   [ ] **Cross-language dedup via embeddings**: Documents are embedded in a
            language-agnostic model. ChromaDB similarity already handles this if we use it.
    *   *Test*: Ingest the same AAPL earnings story from 3 different sources with different
            wording. Verify only the first is scored; the other two are flagged as duplicates.
    *   *Test*: Ingest an AAPL earnings story this quarter and last quarter. Verify they are
            NOT flagged as duplicates despite high term overlap.
        *   Milestone: M3

## Phase 2: Core Algorithm Upgrade (The Engine)
*Status: Blocked by Phase 1*

**Objective**: Rewrite `QueryService.get_top_client_news` to implement the Hybrid Scoring/Bias Logic.

6.  **Refactor Signature & Interface**
    *   [ ] Update `get_top_client_news` to accept `opportunity_bias: float = 0.0`.
    *   [ ] Create `ScoringConfig` dataclass to hold the dynamic weights (derived from $\lambda$) and replace/extend `ClientNewsWeights`.
        *   Milestone: M5

7.  **Implement Hybrid Retrieval (Graph + Vector)**
    *   [ ] **Graph Query**: Enhance existing `_get_documents_for_tickers` to support path counting (influence boost).
    *   [ ] **Vector Query**: Implement `_get_documents_by_vector(mandate_embedding)` using `EmbeddingIndex` when $\lambda > 0.5$.
    *   [ ] **Merge Strategy**: Union results by `document_guid` and track source (`graph` vs `vector`).
        *   Milestone: M6

8.  **Implement Dynamic Scoring Strategy**
    *   [ ] Code the $\lambda$ formulas for Base Score (Holdings vs. Thematic).
    *   [ ] Code the **Exponential Recency** decay ($t_{1/2} = 60m$).
    *   [ ] Code the **Non-Linear Position Boost** (Logarithmic).
    *   [ ] Code the **Influence Boost** (Path counting).
        *   Milestone: M6

## Phase 3: Validating with Simulation (Sunshine & Rain)
*Status: Blocked by Phase 2*

**Objective**: Prove the algo works by generating stress-test scenarios where "Old Algo" fails and "New Algo" succeeds.

9.  **Upgrade Synthetic Story Generator (`generate_synthetic_stories.py`)**
    *   [ ] **Scenario A (Defense)**: "Massive failure in a 0.5% tail holding." (Should likely be ignored/low-ranked unless $\lambda=0.0$).
    *   [ ] **Scenario B (Offense)**: "Competitor M&A in a sector matching Client Mandate." (Should be #1 rank when $\lambda=1.0$).
    *   [ ] **Scenario C (Systemic)**: "Supplier explosion affecting 3 holdings." (Should bubble up via Influence boost).
    *   [ ] **Scenario D (Noise)**: "Generic sector noise." (Should be suppressed).

10. **Refine Avatar Simulation (`validate_avatar_feeds.py`)**
    *   [ ] Add `bias_sweep` mode: Run validation at $\lambda=[0.0, 0.5, 1.0]$.
    *   [ ] **Metric: Recall@3**: How often is the *intended* stress-test story found in the Top 3?
    *   [ ] **Metric: Alpha Score**: (Custom metric measuring relevance of non-holdings).

## Phase 4: Tuning & Calibration (The "Sales Trader" Loop)
*Status: Blocked by Phase 3*

**Objective**: Determine the optimal default weights using quantitative feedback.

11. **Run Large-Scale Simulation**
    *   [ ] `run_simulation.sh --count 500`.
    *   [ ] Inspect `test_output/` JSONs.

12. **Quantify "Bias Sensitivity"**
    *   [ ] Measure crossover point: At what $\lambda$ does a "5-star Competitor News" overtake a "3-star Direct Holding"?
    *   [ ] Calibrate weights to ensure the crossover feels intuitive (e.g., around $\lambda=0.6$).

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

