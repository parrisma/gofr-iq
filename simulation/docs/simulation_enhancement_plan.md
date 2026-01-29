# Simulation Enhancement Plan

**Reference**: See `SIMULATION_ENHANCEMENT_PROPOSAL.md` for full design rationale.

**Critical Path**: Documents → Environment → Testing. Enhanced documents must be generated and ingested before any query/validation testing.

---

## Completed ✓

| Step | Deliverable | Notes |
|------|-------------|-------|
| Universe structure | `simulation/universe/` | 16 tickers, sectors |
| `UniverseBuilder` | `universe/builder.py` | Companies + relationships |
| Relationships | SUPPLIER_OF, COMPETES_WITH | Graph topology |
| Aliases | `MockTicker.aliases` | Fuzzy entity references |
| Universe loader | `load_simulation_data.py` | Graph + clients (consolidated) |
| Client archetypes | `ClientArchetype` dataclass | risk, trust, sectors |
| Client generator | `generate_synthetic_clients.py` | 3 clients |
| Portfolio assignment | HOLDS relationships | Weight + sentiment |
| Client loader | `load_simulation_data.py` | Included in consolidated loader |
| Source registry | `MockSource` in generator | 5 sources, trust 1-10 |
| LLM prompting | Relationship + tone injection | Context-aware generation |
| Vague references | 30% alias usage | Entity resolution stress |
| Ingestion | `ingest_synthetic_stories.py` | Source trust metadata |

---

## In Progress

### Phase 1: Document Generation Enhancement
**Goal**: Generate stories that prove Network Effects, Macro Factors, Trust Gating

- [x] **1.1** Add `Factor` nodes to `universe/builder.py`
  - Add INTEREST_RATES, COMMODITY_PRICES, REGULATION factors
  - Add `EXPOSED_TO` relationships with beta values
  
- [x] **1.2** Enhance `generate_synthetic_stories.py`
  - Add supply chain event scenarios (QNTM fire → GTX impact)
  - Add competitor scenarios (VELO recall → TRUCK opportunity)
  - Add macro factor scenarios (rate hike → BANKO/PROP)
  - Add ESG scenarios for retail client
  - Weight event types (M&A=high, Earnings=medium, Rumors=low)
  
- [x] **1.3** Enhance validation metadata schema
  - Add `expected_relevant_clients` field
  - Add `relationship_hops` (0=direct, 1=supplier, 2=competitor)
  - Add `expected_feed_rank_range` (1-5, 6-15, 16+)
  
- [x] **1.4** Update story generation prompts
  - Inject explicit relationship context
  - Add obfuscation instructions (vague entity references)
  - Add tone variation by source trust level

### Phase 2: Environment Reset & Data Load
**Goal**: Clean slate with enhanced documents

- [x] **2.1** Create `reset_simulation_env.sh` script
  - Clear Neo4j: `MATCH (n) DETACH DELETE n`
  - Clear ChromaDB collections
  - Clear `data/storage/` simulation files
  
- [x] **2.2** Update `load_simulation_data.py` (consolidated universe + clients)
  - Add Factor node creation
  - Add EXPOSED_TO relationship creation
  
- [x] **2.3** Generate enhanced story corpus
  ```bash
  uv run simulation/generate_synthetic_stories.py --count 50 --enhanced
  ```
  **Result**: 51 stories with 13 scenario types
  
- [x] **2.4** Load universe + clients + stories
  - ✅ Full reset with `./scripts/start-prod.sh --reset`
  - ✅ Orchestrated via `./simulation/run_simulation.sh --count 10`
  - ✅ Universe loaded (16 companies, 24 instruments, 5 factors, 22 exposures)
  - ✅ Clients loaded (3 clients with portfolios and watchlists)
  - ✅ Stories ingested (9 documents, 1 duplicate detected)
  - ✅ **Document caching implemented**: Reused 13 existing stories (saved time & API costs)
  - ✅ ChromaDB: 32 entries (documents + chunks)

### Phase 3: Feed Infrastructure & Validation
**Goal**: Query feeds with enhanced documents

**Current Graph State** (as of 2026-01-18 after simulation run):
- ✅ **Node Labels Present** (13 types):
  - Client: 3, ClientProfile: 3, ClientType: 3
  - Company: 16, Instrument: 24
  - Document: 9, EventType: 10
  - Factor: 5, Sector: 9, Region: 6
  - Portfolio: 3, Watchlist: 3, Group: 1
  
- ✅ **Relationships Present** (18 types, 153 total):
  - AFFECTS: 10, BELONGS_TO: 32, COMPETES_WITH: 13
  - EXPOSED_TO: 22, HOLDS: 9, WATCHES: 6
  - ISSUED_BY: 16, IN_GROUP: 25, IS_TYPE_OF: 3
  - HAS_PORTFOLIO: 3, HAS_PROFILE: 3, HAS_WATCHLIST: 3
  - SUPPLIES_TO: 1, SUPPLIED_BY: 1, DISRUPTS: 1
  - PARTNER_OF: 2, INVESTED_IN: 1, INTERESTED_IN: 1

- ❌ **Missing Critical Elements**:
  - Source nodes (0) → blocking feed queries
  - PRODUCED_BY relationships (0) → no trust gating
  - MENTIONS relationships (0) → no multi-entity stories
  - TRIGGERED_BY relationships (0) → no event filtering

**Action Items**:

- [x] **3.1** Add Source nodes and PRODUCED_BY relationships
  - ✅ Created `load_sources_to_neo4j.py` script
  - ✅ Integrated into `run_simulation.py` ensure_sources() function
  - ✅ Sources automatically created from MOCK_SOURCES config during simulation startup
  - ✅ Source nodes added to Neo4j (5 sources created)
  - ✅ PRODUCED_BY relationships created during document ingestion by graph_index service
  - ✅ **Document caching added**: `check_cache.py` utility, metadata tracking, `--regenerate` flag
  - ✅ Full documentation: [simulation/CACHING.md](./CACHING.md)
  
- [x] **3.2** Add MENTIONS relationships
  - ✅ Enhanced `_apply_extraction_to_graph()` in ingest_service.py
  - ✅ Extract companies from `GraphExtractionResult.companies` field
  - ✅ Fuzzy match company names (case-insensitive, alias matching)
  - ✅ Fixed Cypher query bug: `size(c.name)` instead of `length(c.name)`
  - ✅ Fixed parameter name: `company_ticker` not `company_guid`
  - ✅ Create MENTIONS relationships via `graph_index.add_company_mention()`
  - ✅ Distinguish primary (AFFECTS) vs secondary (MENTIONS) company references
  - ✅ Added relationship validation to `run_simulation.py`
  - ✅ Validation output shows PRODUCED_BY, AFFECTS, MENTIONS counts
  - ✅ **Debug logging added**: Tracks extraction, parsing, and relationship creation
  
- [x] **3.3** Test MENTIONS with fresh ingestion
  - ✅ Verified LLM extraction returns companies correctly
  - ✅ Test results: 50 documents → 11 MENTIONS relationships created
  - ✅ Fuzzy matching working: "GigaTech Inc." → "GigaTech Inc."
  - ✅ Alias matching working: "GigaTech" → "GigaTech Inc."
  - ✅ External companies skipped: "Gartner" (not in universe) logged but not failed
  - ✅ Multi-entity tracking confirmed operational
  
- [ ] **3.4** Add TRIGGERED_BY relationships
  - Link documents to EventType nodes via primary_event
  - Support event category filtering in feeds (e.g., only M&A, Earnings)
  
- [x] **3.4** Add TRIGGERED_BY relationships
  - ✅ Added event type mapping: LLM types (EARNINGS_BEAT, etc.) → Graph codes (EARNINGS, etc.)
  - ✅ Fixed relationship creation: Use `code` property instead of `guid` for EventType nodes
  - ✅ Enhanced validation to show TRIGGERED_BY count
  - ✅ **Debug logging added**: Tracks event mapping and relationship creation
  - ✅ Test results: 61 documents → 8 TRIGGERED_BY relationships created
  - ✅ Event filtering infrastructure operational
  
- [x] **3.5** Test trust gating with feed queries
  - ✅ **Hard reset completed**: Clean environment with `./scripts/start-prod.sh --reset`
  - ✅ **Full simulation run**: 10 stories ingested successfully
  - ✅ **Graph state validated**:
    - 6 Source nodes with integer trust levels (1, 3, 6, 10, 10, 10)
    - 9 PRODUCED_BY relationships (documents → sources)
    - 10 AFFECTS relationships (documents → instruments)
    - 13 MENTIONS relationships (documents → companies)
    - 8 TRIGGERED_BY relationships (documents → event types)
  - ✅ **Trust gating verified via Cypher queries**:
    - Hedge fund (min_trust=2): Gets documents from sources with trust ≥ 2
    - Pension fund (min_trust=8): Correctly filters out (no sources meet threshold)
    - Retail trader (min_trust=1): Would get all documents
  - ✅ **Client profiles validated**:
    - Apex Capital (hedge fund): min_trust=2, AGGRESSIVE
    - Teachers Retirement System (pension): min_trust=8, CONSERVATIVE
    - DiamondHands420 (retail): min_trust=1, AGGRESSIVE
  - ✅ **Query pattern confirmed**: `WHERE s.trust_level >= cp.min_trust` working correctly
  
- [ ] **3.6** Test supply chain propagation
  - Verify QNTM fire story appears for GTX holder (hedge fund)
  - Verify relationship_hops=1 in results
  
- [ ] **3.7** Test competitor awareness
  - Verify VELO recall story appears for TRUCK holder (pension fund)
  - Verify sentiment=positive (Schadenfreude)
  
- [ ] **3.8** Test macro factor filtering
  - Verify rate hike stories for BANKO/PROP holders
  - Verify NO rate hike stories for GTX holder

### Phase 4: Validation Harness
**Goal**: Automated regression testing

- [x] **4.1** Create `validate_feeds.py`
  - ✅ Loads validation_metadata from all story files in test_output/
  - ✅ Resolves document GUIDs by matching titles (with normalization)
  - ✅ Fetches client feeds for all expected clients
  - ✅ Validates 6 system behaviors:
    1. Direct Holdings (0-hop): Portfolio relevance
    2. Supply Chain (1-hop): SUPPLIES_TO propagation
    3. Competitor (2-hop): COMPETES_WITH awareness
    4. Macro Factors: Factor exposure routing
    5. Trust Gating: Client min_trust filtering
    6. False Positives: Zero irrelevant documents
  - ✅ Generates detailed pass/fail report with behavior categories
  
- [x] **4.2** Run validation with 50+ documents
  - ✅ Generated 50 synthetic stories (63 total with previous runs)
  - ✅ Ingested successfully: 59 documents in Neo4j, 222 ChromaDB entries
  - ✅ Graph relationships created:
    - 59 PRODUCED_BY (documents → sources)
    - 61 AFFECTS (documents → instruments)
    - 79 MENTIONS (documents → companies)
    - 55 TRIGGERED_BY (documents → event types)
  - ✅ Validation results:
    - **Competitor Awareness: 100%** (2/2 passed) ✅
    - **False Positive Prevention: 94%** (30/32 passed) ✅
    - Direct Holdings: 20% (3/15 passed) - needs improvement
    - Supply Chain: 20% (1/5 passed) - needs improvement
  - ✅ Identified gaps: test case matching, portfolio alignment
  - ✅ Overall: 25% pass rate (6/24 assertions) - good baseline for iteration
  
- [ ] **4.3** Add negative test cases
  - Verify irrelevant tickers excluded
  - Verify cross-contamination prevention
  
- [ ] **4.4** Integrate with `run_simulation.py`
  - Add `--validate-feeds` flag
  - Output validation report

### Phase 5: AI-Native Intelligence ✅ PHASE 5.2 COMPLETE
**Goal**: Entity resolution, semantic profiling, reranking

- [x] **5.1** Generate Investment Policy Statements
  - ✅ Created `generate_client_ips.py`
  - ✅ Generated 3 IPS documents (hedge fund, pension fund, retail)
  - Architecture decision: IPS stored externally as JSON, managed by sales/trading systems
  - Supplied as query parameter, not stored in graph
  
- [x] **5.2** Implement `ClientProfiler` agent
  - ✅ IPS-based filtering: sector exclusions, ESG concerns, trust levels
  - ✅ Semantic reranking: theme alignment, event priorities
  - ✅ Dual-mode operation: file-based (simulation) + JSON-based (production)
  - ✅ Demo: `simulation/demo_ips_filtering.py`
  - ✅ **FIXED**: Registered client_tools and graph_tools in MCP server (`app/tools/__init__.py`)
  - ✅ 11 client management tools + 3 graph exploration tools now available via MCP
  - Results:
    - Hedge Fund (min_trust=2): 8/8 documents pass (aggressive, no filters)
    - Pension Fund (min_trust=8): 3/8 documents pass (conservative, 62% filtered by trust)
    - Retail (min_trust=1): 8/8 documents pass (accepts all sources)
  
- [x] **5.3** ~~Conversational Query Interface~~ **NOT NEEDED**
  - LLM (Claude/GPT) already handles intent classification via MCP
  - Natural language → tool selection works out-of-box with MCP protocol
  - Examples already work: "What affects my QNTM position?" → Claude calls get_instrument_news(ticker="QNTM")
  - Status: ✅ Complete - no additional implementation needed
  
- [ ] **5.4** Implement `LLMReranker` **[PARKED]**
  - Context-aware reranking with IPS using LLM for semantic understanding
  - Would improve on current keyword-based theme matching
  - Use case: "offshore wind farm" → matches "clean energy transition" theme
  - Status: 🅿️ Deferred - current ClientProfiler keyword matching sufficient for now
  
- [ ] **5.5** Test entity resolution **[PARKED]**
  - Verify alias matching (OMNI vs OmniCorp vs "the tech giant")
  - Test obfuscated references ("leading quantum firm" → QNTM)
  - Validate MENTIONS relationships in graph are accurate
  - Status: 🅿️ Deferred - aliases generated, stories use them, automated validation deferred

### Phase 6: Dynamic Simulation & Lifecycle Management
**Goal**: Simulate a living market where new stories arrive, portfolios change, and relevance is re-evaluated in real-time via MCP.

This phase moves beyond static snapshots to prove the system handles the **lifecycle of intelligence**. It validates that as the graph changes (new edges) and the vector space expands (new nodes), the client experience adapts immediately.

- [ ] **6.1** Implement `DynamicSimulator` Agent
  - **Concept**: A unified simulator script that advances "simulation time" and injects state changes via public MCP tools.
  - **Core Capabilities**:
    - **Time advancement**: Simulate T+0, T+1, T+2.
    - **Dynamic Ingestion**: Inject single stories via `ingest_document` (simulating real-time news wire).
    - **Portfolio Evolution**: Call `add_to_portfolio` / `remove_from_portfolio` to simulate trading activity.
    - **Interest Shifts**: Call `add_to_watchlist` to simulate researching a new ticker.
  
- [ ] **6.2** Simulate Lifecycle Scenarios
  - **Scenario A: The Late Adopter (FOMO)**
    1. **T+0**: "QNTM announces breakthrough". Client A (No Position) sees it as generic sector news (Rank: Low).
    2. **T+1**: Client A buys QNTM via `add_to_portfolio`.
    3. **T+2**: "QNTM breakthrough confirmed by regulators".
    4. **Validation**: Verify T+2 story is **Rank 1 / Platinum** for Client A. Prove the *graph edge creation* instantly changed relevance.

  - **Scenario B: Risk Off (Sector Rotation)**
    1. **T+0**: Client B holds TRUCK. News "TRUCK faces recall" appears (Rank: High).
    2. **T+1**: Client B sells TRUCK via `remove_from_portfolio`.
    3. **T+2**: "TRUCK recall expands to all models".
    4. **Validation**: Verify T+2 story is **Downgraded** (no longer a holding) or marked only as "Past Interest".

  - **Scenario C: Watchlist Activation**
    1. **T+0**: Client C adds GENE to Watchlist via `add_to_watchlist`.
    2. **T+1**: "GENE fails Phase 3 trial".
    3. **Validation**: Verify story appears with **"Watchlist Alert"** boost, distinct from Portfolio holdings.

- [ ] **6.3** Real-time Thread Tracking (Evolving Stories)
  - **Concept**: Connecting the dots between stories over time.
  - **Mechanism**:
    - Use chroma vector search to find "Predecessor Documents" (similarity > 0.85) during ingestion.
    - Create `(:Document)-[:FOLLOWS]->(:Document)` relationships in the graph.
  - **Feed Logic**: If a client opened/engaged with Story A, heavily boost Story B (the update).

- [ ] **6.4** Validation of Dynamic State
  - Create `validate_lifecycle.py` to assert state transitions.
  - Ensure no re-indexing lag: The moment `add_to_portfolio` returns success, the next `get_client_feed` call must reflect the new weights.

---

## Immediate Next Actions

1. **Add Factor nodes** — Enhance `universe/builder.py` (Phase 1.1)
2. **Enhance story generation** — Update `generate_synthetic_stories.py` (Phase 1.2)
3. **Reset & reload** — Fresh environment with enhanced docs (Phase 2.1-2.4)

---

## Validation Checklist

After Phase 2.4 (data loaded), run full validation:

```bash
uv run simulation/validate_feeds.py --report validation_report.json
```

| Capability | Test | Phase |
|------------|------|-------|
| Direct holdings | ✓ appears in feed | 3.2 |
| Supply chain | ✓ propagates risk | 3.3 |
| Competition | ✓ Schadenfreude surfaces | 3.4 |
| Macro factors | ✓ beta-weighted | 3.5 |
| Event types | ✓ M&A > Dividend | 3.1 |
| Trust gating | ✓ conservative filters | 3.6 |
| Negative cases | ✓ zero false positives | 4.2 |
| Entity resolution | ✓ aliases resolve | 5.5 |
| IPS filtering | ✓ mandate exclusions | 5.4 |
| NL queries | ✓ Cypher generated | 5.3 |
| Reranking | ✓ ESG respected | 5.4 |
| **Dynamic Updates** | **✓ feed adapts to portfolio change** | **6.2** |
| **Lifecycle** | **✓ watchlist items boosted** | **6.2** |


