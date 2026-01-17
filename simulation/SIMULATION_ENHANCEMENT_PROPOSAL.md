# Simulation Enhancement Proposal

**Objective**: Prove Client-Centric Retrieval-Augmented Story Selection through fundamental market relationships and AI-native intelligence.

---

## Current State

| Component | Status | Gap |
|-----------|--------|-----|
| Universe (16 tickers, relationships) | ✓ | Factor modeling missing |
| Client Archetypes (3 portfolios) | ✓ | Static JSON, no semantic profiles |
| Story Generation (LLM-driven) | ✓ | Clean tickers only, no obfuscation |
| Ingestion (ChromaDB + Neo4j) | ✓ | - |
| Feed Retrieval | ✗ | Query exists in docs, not wired |
| Feed Validation | ✗ | No assertions on results |

---

## Test Document Schema

All synthetic stories must include validation metadata for closed-loop testing:

```json
{
  "source": "Insider Whispers",
  "trust_level": 2,
  "title": "Update regarding major conglomerate",
  "story_body": "...",
  "validation_metadata": {
    "base_ticker": "OMNI",
    "expected_tier": "STANDARD",
    "entity_obfuscation": {
      "level": "full",
      "aliases_used": ["the conglomerate"],
      "expected_resolution": ["OMNI"]
    },
    "relationship_context": {
      "secondary_entities": ["VELO"],
      "relationship_type": "INVESTED_IN",
      "propagation_expected": true
    },
    "client_relevance": {
      "relevant_for": ["hedge-fund"],
      "irrelevant_for": ["pension-fund"]
    },
    "semantic_intent": {
      "should_match_queries": ["management changes"],
      "should_not_match_queries": ["earnings"]
    },
    "factor_exposure": {
      "factors_affected": ["Management_Quality"],
      "sentiment": "NEGATIVE"
    }
  }
}
```

---

## Phase 1-2: Feed Infrastructure (4-6h)

**Deliverables**: `query_client_feed.py`, `validate_feeds.py`

| Test | Assertion |
|------|-----------|
| Direct Holdings | VELO story → Retail client (70% VELO) |
| No Cross-Contamination | VELO story ✗ Pension fund (no VELO) |
| Watchlist | ECO story → Pension fund (watchlist) |

```bash
uv run simulation/query_client_feed.py --client client-hedge-fund --limit 10
uv run simulation/run_simulation.py --validate-feeds
```

---

## Phase 3: Network Effects (3-4h)

**Deliverable**: Multi-hop Cypher queries with relationship context

| Relationship | Test Case |
|--------------|-----------|
| Supply Chain | QNTM fire → GTX holder (QNTM supplies GTX) |
| Competition | VELO recall → TRUCK holder (Schadenfreude) |

```cypher
// Direct + Supply Chain + Competition in single query
MATCH (d:Document)-[:AFFECTS]->(inst:Instrument)
OPTIONAL MATCH (inst)-[:SUPPLIES_TO]->(customer:Instrument)<-[:HOLDS]-(p:Portfolio)
OPTIONAL MATCH (inst)-[:COMPETES_WITH]-(rival:Instrument)<-[:HOLDS]-(p2:Portfolio)
```

---

## Phase 4: Macro Factors (3-4h)

**Deliverable**: Factor nodes + beta exposures in graph

| Factor | High Beta | Low Beta |
|--------|-----------|----------|
| Interest Rates | BANKO (0.9), PROP (0.8) | GTX (0.2) |

**Test**: "Fed Rate Hike" → BANKO/PROP holders, not GTX holders

---

## Phase 5: Ranking Logic (2-3h)

**Deliverable**: Weighted scoring beyond simple tiers

| Priority | Factor |
|----------|--------|
| 1 | Event Type (M&A > Earnings > Dividend) |
| 2 | Position Weight (5% > 1%) |
| 3 | Relationship (Direct > Supplier > Competitor) |
| 4 | Sentiment Inversion (Competitor bad news = opportunity) |

---

## Phase 6: Trust Gating (2h)

**Deliverable**: Source trust filter in feed query

| Client | min_trust | Result |
|--------|-----------|--------|
| Pension Fund | 8 | Filters "Insider Whispers" (trust=2) |
| Hedge Fund | 2 | Sees all sources |
| Retail | 1 | Sees all sources |

---

## Phase 7-8: Negative Cases & CI (3-4h)

**Deliverables**: False positive tests, `--include-simulation` flag

| Test | Assertion |
|------|-----------|
| Irrelevant Ticker | GENE story ✗ Pension fund (no healthcare) |
| Trust Filter | Low-trust source ✗ Conservative client |

```
=== Simulation Validation Report ===
Direct Holdings:     PASS (3/3)
Network Effects:     PASS 
Macro Factors:       PASS
Trust Gating:        PASS
Negative Cases:      PASS (0 false positives)
```

---

## Phase 9: AI-Native Intelligence (8-12h)

Four capabilities requiring both **adversarial test data** and **intelligent implementation**:

### 9.1 Entity Resolution
| Simulation | Implementation |
|------------|----------------|
| Obfuscated stories ("The Cupertino giant") | `graph_extraction.py` resolves to ticker via Knowledge Graph |

### 9.2 Semantic Client Profiling
| Simulation | Implementation |
|------------|----------------|
| Generate Investment Policy Statements (NL) | `ClientProfiler` embeds IPS, filters by mandate constraints |

Example IPS: *"We pursue alpha through volatility arbitrage in liquid tech names, avoiding China exposure due to regulatory uncertainty..."*

### 9.3 Query Translation (NL → Cypher)
| Simulation | Implementation |
|------------|----------------|
| Stories tagged with `semantic_intent` | `QueryTranslationService` converts "Show me supply chain risks" → Cypher |

### 9.4 Agentic Reranking
| Simulation | Implementation |
|------------|----------------|
| ESG-conflicting stories (Coal vs Solar) | `LLMReranker` reorders top-K against client IPS |

**Test**: Pension fund IPS excludes fossil fuels → COAL_CORP (PLATINUM) ranks below SOLAR_CORP (BRONZE)

---

## Implementation Order

| Phase | Effort | Dependency | Deliverable |
|-------|--------|------------|-------------|
| 1-2 | 4-6h | None | Feed infrastructure + basic validation |
| 3 | 3-4h | Phase 2 | Network effects (Supply/Competition) |
| 4 | 3-4h | Phase 3 | Macro factors |
| 5 | 2-3h | Phase 3 | Context-aware ranking |
| 6 | 2h | Phase 2 | Trust gating |
| 7-8 | 3-4h | Phase 6 | Negative cases + CI |
| 9 | 8-12h | Phase 2 | AI-native capabilities |

**Total**: 25-35 hours

---

## Success Criteria

```bash
uv run simulation/run_simulation.py --count 30 --validate-feeds --ai-native
```

Exit 0 when:
- ✓ Direct holdings appear
- ✓ Supply chain risks propagate
- ✓ Competitor events surface (Schadenfreude)
- ✓ Macro events hit sensitive sectors
- ✓ Event types drive ranking over tiers
- ✓ Trust thresholds enforced
- ✓ Obfuscated entities resolve correctly
- ✓ IPS-based filtering excludes violations
- ✓ NL queries translate to correct Cypher
- ✓ Reranking respects client mandates
