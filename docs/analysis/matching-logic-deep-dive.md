# Deep Dive: Client-Document Matching Logic

**Date:** February 2026  
**Author:** GOFR-IQ Engineering  
**Perspective:** Data Science & Agentic Systems Design

---

## 1. The Client Avatar Model

**GOFR-IQ should behave like an intelligent avatar for each client**, scanning the news stream and asking:

> *"Does this story matter to me? Either because it affects what I own, or because it's an opportunity aligned with how I invest?"*

This naturally splits into **two distinct intents**:

| Intent | Question | Priority Signal |
|--------|----------|-----------------|
| **Maintenance** | "What's happening to my positions?" | Holdings/Watchlist overlap |
| **Opportunity** | "What new ideas fit my mandate?" | Theme/strategy alignment, *excluding* current holdings |

**Key Insight:** These are not the same query. Conflating them dilutes both.

---

## 2. Two-Channel Feed Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLIENT AVATAR                               │
│                                                                 │
│   "I am a [mandate_type] investor focused on [themes].         │
│    I currently hold [tickers]. Show me what matters."          │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│   MAINTENANCE CHANNEL   │     │   OPPORTUNITY CHANNEL   │
│   "Protect my book"     │     │   "Find new ideas"      │
├─────────────────────────┤     ├─────────────────────────┤
│ Filter: Doc.instruments │     │ Filter: Doc.themes ∩    │
│   ∩ Client.holdings     │     │   Client.mandate_themes │
│                         │     │                         │
│ EXCLUDE: nothing        │     │ EXCLUDE: Client.holdings│
│ (I need to know even    │     │ (I already own these,   │
│  bad news about my      │     │  not a "new" idea)      │
│  positions)             │     │                         │
├─────────────────────────┤     ├─────────────────────────┤
│ Score: impact × recency │     │ Score: theme_fit ×      │
│                         │     │   impact × recency      │
├─────────────────────────┤     ├─────────────────────────┤
│ Why: "Affects your AAPL │     │ Why: "Matches your      │
│   position"             │     │   clean_energy focus"   │
└─────────────────────────┘     └─────────────────────────┘
              │                               │
              └───────────────┬───────────────┘
                              ▼
                    ┌─────────────────┐
                    │  MERGED FEED    │
                    │  (labeled by    │
                    │   channel)      │
                    └─────────────────┘
```

---

## 3. Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Deterministic** | Same input → same output. No LLM at query time. |
| **Fast** | <200ms. Pure graph/filter operations. |
| **Explainable** | Every result tagged: `reason=HOLDING` or `reason=OPPORTUNITY` |
| **Cost-Efficient** | LLM work at ingest/profile-update only. Query = $0.00. |

---

## 4. Precomputation Strategy

All intelligence happens **before** query time:

### 4.1 At Document Ingest (Existing + Extended)

```
Document ──► LLM Extraction ──► Stored Properties
                │
                ├── impact_score (0-100)
                ├── impact_tier (PLATINUM/GOLD/...)
                ├── event_type (EARNINGS_BEAT, M&A, ...)
                ├── instruments[] (tickers directly affected)
                ├── themes[]  ◄── NEW: ["ev_battery", "china", "supply_chain"]
                └── sectors[] (for peer matching)
```

**Cost:** ~$0.002/doc. Amortized across all clients.

### 4.2 At Client Profile Update (New)

When `mandate_text` or `mandate_type` changes:

```
Profile ──► LLM Analysis ──► Stored Properties
                │
                ├── mandate_themes[]   e.g., ["clean_energy", "japan", "robotics"]
                ├── event_preferences  e.g., {M&A: 1.5, EARNINGS: 1.0}
                └── opportunity_keywords[] for semantic backup
```

**Cost:** ~$0.01/update. One-time per profile change.

---

## 5. Query-Time Logic (Zero LLM)

```python
def get_client_feed(client_guid: str, limit: int = 10) -> Feed:
    profile = load_profile(client_guid)
    holding_tickers = get_holdings(client_guid) + get_watchlist(client_guid)
    
    # ─────────────────────────────────────────────────────────
    # CHANNEL 1: MAINTENANCE (news about what I own)
    # ─────────────────────────────────────────────────────────
    maintenance_docs = neo4j.query("""
        MATCH (d:Document)-[:AFFECTS]->(i:Instrument)
        WHERE i.ticker IN $holding_tickers
          AND d.created_at > $cutoff
        RETURN d.guid, d.title, d.impact_score, i.ticker as matched_ticker
    """, holding_tickers=holding_tickers)
    
    for doc in maintenance_docs:
        doc.channel = "MAINTENANCE"
        doc.reason = f"Affects your {doc.matched_ticker} position"
        doc.score = doc.impact_score * recency_factor(doc)
    
    # ─────────────────────────────────────────────────────────
    # CHANNEL 2: OPPORTUNITY (new ideas matching mandate)
    # ─────────────────────────────────────────────────────────
    if profile.mandate_themes:
        opportunity_docs = neo4j.query("""
            MATCH (d:Document)
            WHERE d.created_at > $cutoff
              AND any(t IN d.themes WHERE t IN $mandate_themes)
              AND NOT any(i IN d.instruments WHERE i IN $holding_tickers)
            RETURN d.guid, d.title, d.impact_score, d.themes
        """, mandate_themes=profile.mandate_themes, holding_tickers=holding_tickers)
        
        for doc in opportunity_docs:
            doc.channel = "OPPORTUNITY"
            matched = set(doc.themes) & set(profile.mandate_themes)
            doc.reason = f"Matches your {', '.join(matched)} focus"
            doc.score = theme_fit(doc, profile) * doc.impact_score * recency_factor(doc)
    
    # ─────────────────────────────────────────────────────────
    # MERGE & RANK
    # ─────────────────────────────────────────────────────────
    all_docs = dedupe(maintenance_docs + opportunity_docs)
    all_docs.sort(by='score', descending=True)
    
    return Feed(
        maintenance=[d for d in all_docs if d.channel == "MAINTENANCE"][:limit//2],
        opportunity=[d for d in all_docs if d.channel == "OPPORTUNITY"][:limit//2],
        combined=all_docs[:limit]
    )
```

---

## 6. Scoring Formulas

### Maintenance Score (Holdings-Based)
```
score = impact_norm × recency × position_weight

Where:
- impact_norm = doc.impact_score / 100
- recency = exp(-0.15 × days_old)
- position_weight = holding_weight or 1.0 if watchlist
```

Higher impact + more recent + larger position = higher score.

### Opportunity Score (Mandate-Based)
```
score = theme_fit × impact_norm × recency × novelty_boost

Where:
- theme_fit = |doc.themes ∩ profile.mandate_themes| / |profile.mandate_themes|
- novelty_boost = 1.2 if doc.event_type in [M&A, IPO, PRODUCT_LAUNCH] else 1.0
```

Better theme overlap + higher impact + "actionable" event types = higher score.

---

## 7. Example Feed Output

```json
{
  "client_guid": "abc-123",
  "generated_at": "2026-02-06T10:00:00Z",
  "maintenance": [
    {
      "title": "Apple Q1 earnings beat estimates",
      "channel": "MAINTENANCE",
      "reason": "Affects your AAPL position (12% of portfolio)",
      "impact_tier": "GOLD",
      "score": 0.85
    },
    {
      "title": "Tesla recalls 50,000 vehicles",
      "channel": "MAINTENANCE", 
      "reason": "Affects your TSLA position",
      "impact_tier": "SILVER",
      "score": 0.62
    }
  ],
  "opportunity": [
    {
      "title": "Rivian secures $5B battery supply deal",
      "channel": "OPPORTUNITY",
      "reason": "Matches your clean_energy, ev_battery focus",
      "impact_tier": "GOLD",
      "score": 0.71
    },
    {
      "title": "Japan robotics exports hit record high",
      "channel": "OPPORTUNITY",
      "reason": "Matches your japan, robotics focus",
      "impact_tier": "SILVER", 
      "score": 0.58
    }
  ]
}
```

---

## 8. What NOT To Do

| Anti-Pattern | Why It Fails |
|--------------|--------------|
| LLM relevance check at query time | Slow, expensive, non-deterministic |
| Single merged query for both intents | Dilutes both maintenance AND opportunity signals |
| Including holdings in opportunity search | Defeats the purpose—those aren't "new" ideas |
| Complex multi-hop graph walks at runtime | Unbounded latency; precompute relationships instead |

---

## 9. Step-by-Step Transformation Plan (Test-Gated)

This is designed as a **small-step migration**: each step is shippable, testable, and keeps query-time deterministic.

### Test discipline
- Always run infra-aware tests via `./scripts/run_tests.sh` (never raw `pytest`).
- Prefer “add a test first” for every new behavior.

### Step 0 — Baseline + guardrails (no behavior change)
**Goal:** lock in current behavior so we can prove improvements.

- Add a snapshot-style unit test around the current `QueryService.get_top_client_news()` output shape (keys present, sorted by `relevance_score`, stable reasons set).
- Add a small integration test that asserts **holdings news outranks non-holdings news** (this already exists conceptually in `test/test_graph_index.py`; mirror it at the service layer if needed).

**Test gate:**
- `./scripts/run_tests.sh --check`
- `./scripts/run_tests.sh test/test_query_service.py -k "top_client_news"`

### Step 1 — Add document `themes[]` at ingest-time (schema + parsing)
**Goal:** enable opportunity matching without query-time LLM.

- Extend `GraphExtractionResult` and parsing to include optional `themes: list[str]` (default `[]`).
- Update the extraction prompt to ask for themes in a **small controlled vocabulary** (e.g., `supply_chain`, `ai`, `ev_battery`, `japan`, `china`, `rates`, `fx`, `credit`, `m_and_a`).

**Tests to add:**
- Parsing test: JSON with `themes` round-trips and defaults correctly.
- Backward-compat test: old JSON responses without `themes` still parse.

**Test gate:**
- `./scripts/run_tests.sh test/test_integration_hybrid_query.py -k "extraction"`

### Step 2 — Persist `themes[]` onto the Document node (graph index)
**Goal:** make `themes` queryable in Neo4j (fast filters).

- Update graph write path so `Document` nodes store `themes` (and optionally `sectors`, `regions` if we want them consistent).
- Add or update Neo4j indexes/constraints if needed (property index on `Document(themes)` is optional; a list-property index may or may not help depending on Neo4j version—measure before committing).

**Tests to add:**
- Graph test: create a document with themes and assert they are stored/readable via Cypher.

**Test gate:**
- `./scripts/run_tests.sh test/test_graph_index.py -k "document"`

### Step 3 — Introduce a new “Avatar Feed” API (do not break existing output)
**Goal:** ship the two-channel model without destabilizing existing clients/UI.

- Add a new method (example naming): `QueryService.get_client_avatar_feed(...)` that returns:
  - `maintenance: list[FeedItem]`
  - `opportunity: list[FeedItem]`
  - `combined: list[FeedItem]`
  - Each item includes `channel` + `reason`.
- Keep `get_top_client_news()` intact for now.

**Tests to add:**
- Unit test: holdings story appears in `maintenance`.
- Unit test: mandate-themed story appears in `opportunity`.
- Unit test: a holdings story is **excluded from opportunity** (novelty guard).

**Test gate:**
- `./scripts/run_tests.sh test/test_query_service.py -k "avatar"`

### Step 4 — Minimal client mandate themes (no LLM required)
**Goal:** get opportunity matching working deterministically without any enrichment pipeline.

- Add an optional `ClientProfile.mandate_themes` property (stored as JSON string or list—choose whichever matches existing storage patterns).
- Allow the UI/MCP to set it explicitly (manual curation is fine to start).

**Tests to add:**
- MCP tool test: update client profile with `mandate_themes` and confirm it’s returned.

**Test gate:**
- `./scripts/run_tests.sh test/test_mcp_tools.py -k "client_profile"`

### Step 5 — Optional async mandate-to-themes enrichment (LLM at update-time only)
**Goal:** leverage agentic capability without query-time cost/nondeterminism.

- Add a background enrichment job that runs only when `mandate_text` changes.
- Store results (`mandate_themes`, `event_preferences`) on the profile.
- Make it **idempotent** and cacheable (hash of mandate_text).

**Tests to add:**
- Deterministic test in mock mode: given a fixed mandate_text, enrichment returns a stable theme set.

**Test gate:**
- `./scripts/run_tests.sh -k "mandate"`

### Step 6 — Switch simulation validation to prove the two-channel value
**Goal:** demonstrate measurable improvement using controlled data.

- Extend synthetic story generator to include `validation_metadata` that explicitly encodes:
  - expected channel (`MAINTENANCE` vs `OPPORTUNITY`)
  - expected relevant clients
  - “novelty” expectation (should not match holdings)
- Extend synthetic client generator to include `mandate_themes` (or restrictions-based themes) aligned to archetypes.
- Update `simulation/validate_feeds.py` (or add a new validator) to assert:
  - Maintenance scenarios land in maintenance.
  - Opportunity scenarios land in opportunity.
  - Opportunity never returns a client’s own holdings.

**Test gate:**
- Add a lightweight test that runs the validator against a tiny fixed dataset (5 clients, 20 docs) in CI.

---

## 10. Proving Value with Simulation (Designed + Measured)

To prove the algorithm, the simulation needs **ground truth** and **metrics**, not just plausible text.

### 10.1 Designed datasets (ground truth)
Add scenario families that isolate each capability:

| Family | What it proves | How |
|--------|----------------|-----|
| Maintenance-Direct | holdings matching works | doc affects holding instrument |
| Maintenance-Watchlist | soft interest works | doc affects watchlist ticker |
| Opportunity-Themes | mandate matching works | doc themes overlap mandate_themes |
| Opportunity-Novelty | “new ideas” works | doc matches mandate_themes but excludes holdings |
| ESG Kill | exclusions still enforced | doc tagged to excluded sector/company |

### 10.2 Metrics (offline evaluation)
Compute metrics separately per channel:

- **Maintenance Precision@K**: fraction of maintenance results that are truly holdings/watchlist-related.
- **Opportunity Precision@K**: fraction of opportunity results that match mandate_themes and are novel.
- **Opportunity Novelty@K**: fraction of opportunity results with **no holdings overlap**.
- **Coverage**: fraction of labeled scenarios correctly surfaced in top K.
- **Stability**: identical inputs produce identical outputs across runs.

### 10.3 A/B evaluation harness
Add a simulation runner mode that can compare:

- **Baseline**: current `get_top_client_news()` logic.
- **Avatar**: new two-channel feed logic.

Output a compact report:
- per-scenario pass/fail
- per-channel precision/novelty
- deltas vs baseline

---

## 11. Summary

**The Client Avatar Model:**
- **Maintenance:** "What's happening to my book?" → holdings/watchlist-driven matching
- **Opportunity:** "What new ideas fit my style?" → mandate-driven matching, explicitly excluding current holdings

**Key Design:**
- Agentic intelligence happens at ingest/update time (themes/preferences), never at query time
- Query time stays deterministic: graph + filters + scoring
- Simulation becomes a measurement system with ground truth, not just demo data

**Result:** You can prove (with numbers) that opportunity discovery improves without sacrificing maintenance relevance, while keeping runtime fast and cost-free.
