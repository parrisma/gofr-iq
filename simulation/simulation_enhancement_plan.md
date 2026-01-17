# Simulation Enhancement Plan

**Reference**: See `SIMULATION_ENHANCEMENT_PROPOSAL.md` for full design rationale.

---

## Completed ✓

| Step | Deliverable | Notes |
|------|-------------|-------|
| Universe structure | `simulation/universe/` | 16 tickers, sectors |
| `UniverseBuilder` | `universe/builder.py` | Companies + relationships |
| Relationships | SUPPLIER_OF, COMPETES_WITH | Graph topology |
| Aliases | `MockTicker.aliases` | Fuzzy entity references |
| Universe loader | `load_universe_to_neo4j.py` | Graph injection |
| Client archetypes | `ClientArchetype` dataclass | risk, trust, sectors |
| Client generator | `generate_synthetic_clients.py` | 3 clients |
| Portfolio assignment | HOLDS relationships | Weight + sentiment |
| Client loader | `load_clients_to_neo4j.py` | Portfolios + watchlists |
| Source registry | `MockSource` in generator | 5 sources, trust 1-10 |
| LLM prompting | Relationship + tone injection | Context-aware generation |
| Vague references | 30% alias usage | Entity resolution stress |
| Ingestion | `ingest_synthetic_stories.py` | Source trust metadata |

---

## In Progress

### Phase 1-2: Feed Infrastructure
- [ ] **1.1** Create `query_client_feed.py` with basic Cypher
- [ ] **1.2** Add CLI: `--client <guid> --limit N`
- [ ] **1.3** Create `validate_feeds.py` harness
- [ ] **1.4** Test: Direct holdings appear in feed
- [ ] **1.5** Test: No cross-contamination
- [ ] **1.6** Add `--validate-feeds` to `run_simulation.py`

### Phase 3: Network Effects
- [ ] **3.1** Extend Cypher for 2-hop supply chain
- [ ] **3.2** Extend Cypher for competitor traversal
- [ ] **3.3** Test: QNTM fire → GTX holder
- [ ] **3.4** Test: VELO recall → TRUCK holder (Schadenfreude)

### Phase 4: Macro Factors
- [ ] **4.1** Add `Factor` nodes to `UniverseBuilder`
- [ ] **4.2** Add `EXPOSED_TO` edges with beta values
- [ ] **4.3** Update `load_universe_to_neo4j.py`
- [ ] **4.4** Generate macro event stories
- [ ] **4.5** Test: Rate hike → BANKO/PROP, not GTX

### Phase 5: Ranking Logic
- [ ] **5.1** Implement event type weights (M&A > Earnings)
- [ ] **5.2** Implement position weight boost
- [ ] **5.3** Implement relationship distance penalty
- [ ] **5.4** Test: Ranking assertions pass

### Phase 6: Trust Gating
- [ ] **6.1** Verify `min_trust` on ClientProfile
- [ ] **6.2** Add trust filter to feed query
- [ ] **6.3** Test: Pension fund filters trust < 8

### Phase 7-8: Negative Cases & CI
- [ ] **7.1** Test: Irrelevant ticker excluded
- [ ] **7.2** Test: Watchlist content surfaces
- [ ] **7.3** Add `--include-simulation` to test runner
- [ ] **7.4** Implement validation report output

### Phase 9: AI-Native
- [ ] **9.1** Obfuscation layer in story generator
- [ ] **9.2** Enhanced validation metadata schema
- [ ] **9.3** Generate Investment Policy Statements
- [ ] **9.4** `ClientProfiler` agent + embeddings
- [ ] **9.5** `QueryTranslationService` (NL → Cypher)
- [ ] **9.6** `LLMReranker` with IPS context
- [ ] **9.7** Test: Entity resolution with aliases
- [ ] **9.8** Test: IPS-based filtering
- [ ] **9.9** Test: NL query translation
- [ ] **9.10** Test: ESG-aware reranking

---

## Immediate Next Actions

1. **query_client_feed.py** — Wire feed retrieval (Phase 1.1)
2. **Factor nodes** — Add to UniverseBuilder (Phase 4.1-4.3)

---

## Validation Checklist

```bash
uv run simulation/run_simulation.py --count 30 --validate-feeds --ai-native
```

| Capability | Test |
|------------|------|
| Direct holdings | ✓ appears in feed |
| Supply chain | ✓ propagates risk |
| Competition | ✓ Schadenfreude surfaces |
| Macro factors | ✓ beta-weighted |
| Event types | ✓ M&A > Dividend |
| Trust gating | ✓ conservative filters |
| Negative cases | ✓ zero false positives |
| Entity resolution | ✓ aliases resolve |
| IPS filtering | ✓ mandate exclusions |
| NL queries | ✓ Cypher generated |
| Reranking | ✓ ESG respected |
