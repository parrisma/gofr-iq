# Implementation Plan: Graph-Based News Ranking & Client Matching

This document outlines the iterative plan to upgrade the Gofr-IQ platform with advanced graph capabilities for news ranking, event detection, and client-specific relevance matching.

## Phase 1: Graph Model Upgrade (Schema & Core Service)

**Objective**: Update the Neo4j schema to support the new rich domain model (Instruments, Events, Clients) and enhance the `GraphIndex` service to manage these new entities.

### Tasks
1.  **Update `NodeLabel` Enum**: Add `INSTRUMENT`, `INDEX`, `FACTOR`, `EVENT_TYPE`, `CLIENT_TYPE`, `CLIENT`, `CLIENT_PROFILE`, `PORTFOLIO`, `WATCHLIST`, `POSITION`.
2.  **Update `RelationType` Enum**: Add `AFFECTS`, `TRIGGERED_BY`, `RELEVANT_TO`, `DELIVERED_TO`, `HOLDS`, `WATCHES`, `BENCHMARKED_TO`, `EXCLUDES`, `SUBSCRIBED_TO`, `EXPOSED_TO`, `PEER_OF`, `CONSTITUENT_OF`, `ISSUED_BY`, `TRACKS`, `IS_TYPE_OF`, `HAS_PROFILE`, `HAS_PORTFOLIO`, `HAS_WATCHLIST`.
3.  **Enhance `GraphIndex` Service**:
    *   Add methods to create/update these specific node types with their unique properties (e.g., `create_instrument`, `create_client`).
    *   Implement the "Group as Permission Gate" logic: Ensure all content queries enforce `IN_GROUP` checks.
    *   Add schema initialization for new constraints and indexes (e.g., `instrument_guid`, `ticker_symbol`).
4.  **Unit Tests**: Update `test_graph_index.py` to verify new enums, node creation, and constraint application.

### Deliverable
*   Updated `app/services/graph_index.py`
*   Updated `test/test_graph_index.py` passing all tests.

---

## Phase 2: LLM Service Integration (OpenRouter)

**Objective**: Enable the application to perform semantic reasoning, extraction, and embedding generation using an external LLM (via OpenRouter).

### Tasks
1.  **Configuration**: Add `GOFR_IQ_OPENROUTER_API_KEY`, `GOFR_IQ_LLM_MODEL`, and `GOFR_IQ_EMBEDDING_MODEL` to `app/config.py` and environment variables.
2.  **LLM Service**: Create `app/services/llm_service.py`.
    *   Implement a client for OpenRouter (compatible with OpenAI API).
    *   Add methods for `chat_completion` with support for structured outputs (JSON mode) and system prompts.
    *   Add methods for `generate_embedding` to produce vectors for ChromaDB storage.
    *   Implement error handling, retries, and rate limiting.
3.  **Embedding Integration**: Update `app/services/embedding_index.py` to optionally use the LLM service for embeddings.
    *   When `GOFR_IQ_OPENROUTER_API_KEY` is set, use OpenRouter embeddings instead of ChromaDB's default.
    *   Support configurable embedding model (e.g., `text-embedding-3-small`).
    *   Maintain backward compatibility with ChromaDB's built-in embeddings when no API key is provided.
4.  **Unit Tests**: Create `test/test_llm_service.py` (mocked tests for all methods).
5.  **Integration Tests**: Create `test/test_integration_llm.py` (live tests, skipped when API key not available).
    *   Test chat completion with structured JSON output.
    *   Test embedding generation and verify vector dimensions.
    *   Test embedding storage/retrieval through ChromaDB with LLM-generated embeddings.

### Test Support
*   Tests should auto-detect LLM capability via environment variable presence.
*   When `GOFR_IQ_OPENROUTER_API_KEY` is not set:
    *   Unit tests use mocked responses.
    *   Integration tests are skipped with clear message.
*   When API key is set:
    *   Live integration tests verify end-to-end functionality.
    *   Use low-cost models for testing (e.g., `meta-llama/llama-3.1-8b-instruct`).

### Deliverable
*   `app/services/llm_service.py` with `chat_completion()` and `generate_embedding()` methods
*   Updated `app/services/embedding_index.py` with LLM embedding support
*   `test/test_llm_service.py` (mocked unit tests)
*   `test/test_integration_llm.py` (live integration tests, conditionally skipped)

---

## Phase 3: Graph Extraction Prompt & Ingestion Logic

**Objective**: Develop the "Brain" that converts raw text into structured graph updates.

### Tasks
1.  **Prompt Engineering**: Design the system prompt (`app/prompts/graph_extraction.py`).
    *   **Input**: Document text, metadata.
    *   **Output**: JSON structure containing:
        *   `impact_score` (0-100), `impact_tier`.
        *   `events`: List of detected events (Type, Confidence).
        *   `instruments`: List of affected instruments (Ticker, Direction, Magnitude).
        *   `companies`: Mentions.
        *   `summary`: One-line summary.
    *   **Instructions**: detailed rules for scoring and classification based on the "News Impact Ranking Scale".
2.  **Ingest Service Update**: Modify `app/services/ingest_service.py`.
    *   Inject `LLMService` dependency.
    *   In `ingest()`, after storing the document, call `LLMService` with the extraction prompt.
    *   Parse the LLM response.
    *   Call `GraphIndex` to update the graph:
        *   Set Document properties (`impact_score`, etc.).
        *   Create `AFFECTS` relationships to Instruments.
        *   Create `TRIGGERED_BY` relationships to EventTypes.
        *   Create `MENTIONS` relationships.

### Deliverable
*   `app/prompts/graph_extraction.py`
*   Updated `app/services/ingest_service.py`
*   Unit tests for prompt construction and response parsing.

---

## Phase 4: Client Persona & Query Logic

**Objective**: Implement the logic to match stories to clients based on the graph.

### Tasks
1.  **Client Management Tools**: Create `app/tools/client_tools.py` (or add to `graph_tools.py`).
    *   `create_client_profile`: Setup a client with portfolio, watchlist, and preferences.
    *   `get_client_feed`: The core ranking algorithm (Cypher query) that returns the top N stories for a client.
2.  **Cypher Query Implementation**:
    *   Implement the "Score a Story for a Client" query from `graph_architecture.md`.
    *   Implement the "Time-Decayed Relevance" logic.
    *   Ensure `IN_GROUP` permissioning is strict.

### Deliverable
*   Updated `app/services/graph_index.py` with `get_client_feed` method.
*   `app/tools/client_tools.py` (MCP tools for client management).

---

## Phase 5: Enhanced MCP Tools & Annotation

**Objective**: Expose the new capabilities to the Agent/LLM with rich metadata for autonomous navigation.

### Tasks
1.  **Update `query_tools.py`**:
    *   Enhance `query_documents` to support "impact" and "client" filters.
2.  **New `graph_tools.py`**:
    *   `explore_graph`: Allow the agent to traverse from a node (e.g., "What else affects AAPL?").
    *   `get_market_context`: Retrieve related events and peers for an instrument.
3.  **Tool Annotations**: Ensure all tools have comprehensive docstrings and type hints for optimal LLM usage.

### Deliverable
*   Updated `app/tools/query_tools.py`
*   New `app/tools/graph_tools.py`

---

## Phase 6: End-to-End Integration Testing

**Objective**: Verify the entire pipeline from ingestion to client-specific retrieval with proper group-based content isolation.

### Tasks
1.  **Test Groups**: Define 3 test groups representing different content sources:
    *   **Group A** ("Sales Team NYC"): Internal sales intelligence
    *   **Group B** ("Reuters Feed"): Premium newswire content
    *   **Group C** ("Alternative Data"): Proprietary data vendor
2.  **Test Data**: Create synthetic news articles distributed across groups:
    *   Group A: Tech earnings (AAPL, NVDA), M&A rumors from sales contacts
    *   Group B: Macro events (Fed decisions), official announcements
    *   Group C: Quant signals, alternative data insights
3.  **Test Clients**: Define 3 client profiles with different group access permissions:
    *   **Hedge Fund client**: Has tokens for Groups A, B, C (full access)
    *   **Long-Only client**: Has tokens for Groups A, B only (no alternative data)
    *   **Basic client**: Has token for Group B only (newswire only)
4.  **Integration Test Suite** (`test/test_integration_graph_ranking.py`):
    *   **Step 1**: Create groups, sources, and ingest articles with correct group ownership (mocking LLM extraction).
    *   **Step 2**: Verify Graph State - documents have correct `IN_GROUP` relationships.
    *   **Step 3**: Verify ChromaDB isolation - embeddings tagged with group metadata.
    *   **Step 4**: Query with Group B token only -> Only see Group B documents.
    *   **Step 5**: Query with Groups A,B tokens -> See A and B content, never C.
    *   **Step 6**: Query with all tokens (A,B,C) -> See everything.
    *   **Step 7**: Client feed uses passed group_guids to filter content appropriately.

### Deliverable
*   `test/test_integration_graph_ranking.py`

---

## Phase 7: Refinement & Tuning

**Objective**: Analyze results and tune the model.

### Tasks
1.  **Analyze Gaps**: Review where the graph model failed to capture nuance in Phase 6.
2.  **Tune Prompt**: Refine the extraction prompt for better accuracy.
3.  **Tune Weights**: Adjust the scoring weights in the Cypher queries (e.g., increase weight of `WATCHLIST` vs `PORTFOLIO`).
4.  **Performance**: Check query performance and add missing indexes.

### Deliverable
*   Refined code and configuration.
*   Final `IMPLEMENTATION_STATUS.md` update.

---

## Phase 8: Hybrid Query Integration Testing (Graph + Semantic)

**Objective**: Verify that queries benefit from BOTH relational graph traversal AND semantic similarity, demonstrating superior results compared to either system alone.

### Conceptual Foundation

The current architecture maintains two complementary indexes:

1. **ChromaDB (Semantic)**: Vector embeddings capture "aboutness" - documents semantically similar to a query are retrieved regardless of explicit entity mentions.

2. **Neo4j (Relational)**: Graph relationships capture explicit structure - documents are connected via shared entities, events, instruments, and lateral relationships (peer companies, supply chain, sector).

**The Power of Hybrid**: Neither system alone captures the full picture:

| Query Type | Semantic Only | Graph Only | Hybrid |
|------------|---------------|------------|--------|
| "Federal Reserve interest rates" | ✅ Finds Fed articles | ❌ Misses unless "Fed" node exists | ✅ Best of both |
| "What affects AAPL?" | ⚠️ Keyword match luck | ✅ AFFECTS relationships | ✅ Relations + similar |
| "Peer read-through from NVDA earnings" | ❌ No AMD mention | ✅ PEER_OF traversal | ✅ NVDA semantic + AMD peers |
| "Tech sector momentum" | ✅ Topical similarity | ⚠️ Needs sector graph | ✅ Sector + semantic |

### The Query Gap Problem

**Current State**: `QueryService.query()` does:
1. ChromaDB semantic search → similarity scores
2. Optional graph enrichment → adds `graph_context` to results

**Gap**: The graph is used for *enrichment* but not for *retrieval expansion*. We're missing:
- **Graph-expanded retrieval**: Start with semantic hits, then traverse graph to find *related* documents that semantic search missed
- **Multi-hop relevance**: Document A mentions AAPL → AAPL PEER_OF AMD → Document B mentions AMD (semantic wouldn't connect A↔B)
- **Event propagation**: Earnings warning for AAPL → CONSTITUENT_OF QQQ → Other QQQ holdings potentially affected

### Test Scenarios (Live LLM Integration)

#### Scenario 1: Single-Stock Direct Query
**Input**: "Apple iPhone sales decline"
**Expected Semantic Hits**: Direct AAPL articles mentioning iPhone
**Expected Graph Expansion**:
- Documents with AFFECTS→AAPL relationship (even if "iPhone" not mentioned)
- Peer read-through via PEER_OF to Samsung, Xiaomi articles
- Supply chain via ISSUED_BY to component suppliers

**Success Criteria**: Hybrid returns at least 20% more relevant results than semantic-only

#### Scenario 2: Instrument Traversal Query  
**Input**: "semiconductor supply chain disruption"
**Expected Semantic Hits**: Articles about chips, supply chain, shortages
**Expected Graph Expansion**:
- NVDA → AFFECTS documents → traverse PEER_OF → AMD, INTC documents
- Sector traversal: Tech sector → all tech instruments → AFFECTS relationships
- Event type: MACRO_DATA events about manufacturing

**Success Criteria**: Graph-expanded results include articles never mentioning "semiconductor" directly but affecting related instruments

#### Scenario 3: Event Propagation Query
**Input**: "Impact of Fed rate decision"
**Expected Semantic Hits**: Fed, interest rate, monetary policy articles
**Expected Graph Expansion**:
- CENTRAL_BANK events → affect financials → bank stocks
- Index impact: SPY, QQQ affected → constituent companies
- Cross-market: Bond-related articles via factor relationships

**Success Criteria**: Results span multiple asset classes connected via graph relationships

#### Scenario 4: Lateral Discovery (Pure Graph Value)
**Input**: Query for "TSLA" articles, but user interested in competitors
**Test**: 
1. User queries "Tesla production numbers"
2. Graph traverses PEER_OF→ RIVN, LCID, NIO
3. Returns relevant peer articles user didn't explicitly ask for

**Success Criteria**: Results include competitor news that semantic search alone wouldn't surface

#### Scenario 5: Historical Pattern Query
**Input**: "Similar to the 2022 crypto winter"
**Expected Semantic Hits**: Crypto crash, Bitcoin decline, exchange failures
**Expected Graph Expansion**:
- CRYPTO instruments → historical AFFECTS relationships
- Similar EVENT_TYPES from past documents
- Connected companies (COIN, MSTR) via ISSUED_BY

**Success Criteria**: Historical pattern matching via event type + semantic similarity

### Implementation Steps

#### Step 1: Test Infrastructure Setup
```
test/test_integration_hybrid_query.py
```
- Configure real ChromaDB (existing test infrastructure)
- Configure real Neo4j (existing test infrastructure)  
- Configure LLM service with API key (skip if not available)
- Create test fixtures with realistic financial news

#### Step 2: Ingest Phase (Live LLM)
1. Create 3 test groups (Sales, Newswire, Vendor) - reuse from Phase 6
2. Create 15-20 test articles covering:
   - Direct instrument mentions (AAPL, NVDA, TSLA)
   - Peer companies (AMD, INTC, RIVN)
   - Macro events (Fed decisions, CPI data)
   - Sector-wide news (Tech earnings season)
   - Supply chain articles (TSMC, chip shortage)
3. **Critical**: Ingest with live LLM to populate:
   - ChromaDB embeddings (semantic vectors)
   - Neo4j graph (AFFECTS, TRIGGERED_BY, MENTIONS relationships)
   - Impact scores and event types

#### Step 3: Verify Dual Population
Tests to confirm ingestion populated both systems:
```python
def test_chromadb_has_embeddings():
    """Verify all documents have vector embeddings"""
    
def test_neo4j_has_relationships():
    """Verify documents have AFFECTS, TRIGGERED_BY relationships"""
    
def test_instruments_created():
    """Verify extracted instruments exist as nodes"""
    
def test_event_types_linked():
    """Verify event type relationships created"""
```

#### Step 4: Semantic-Only Baseline
Run queries using ChromaDB only (disable graph):
```python
def test_semantic_only_direct_query():
    """Baseline: Query 'AAPL earnings' semantic-only"""
    
def test_semantic_only_misses_peers():
    """Verify semantic misses peer-related docs"""
```

#### Step 5: Graph-Expanded Queries
Implement and test graph-expanded retrieval:
```python
def test_graph_expands_to_peers():
    """AAPL query finds AMD docs via PEER_OF"""
    
def test_graph_expands_to_affected_instruments():
    """Sector query finds individual stocks via AFFECTS"""
    
def test_event_propagation():
    """Fed event finds affected sector documents"""
```

#### Step 6: Hybrid Scoring
Test combined scoring from both systems:
```python
def test_hybrid_score_combines_semantic_and_graph():
    """Verify final score = α×semantic + β×graph_relevance"""
    
def test_hybrid_ranks_better_than_either_alone():
    """Precision@10 improves with hybrid"""
```

#### Step 7: Relevance Metrics
Compute and assert relevance improvements:
- Precision@K for hybrid vs semantic-only
- Recall improvement from graph expansion
- Mean Reciprocal Rank (MRR) comparison

### Test Data Requirements

**Articles to Ingest (15-20)**:

| ID | Title | Instruments | Event Type | Group |
|----|-------|-------------|------------|-------|
| 1 | "Apple Q4 Earnings Beat Expectations" | AAPL | EARNINGS_BEAT | A |
| 2 | "Samsung Reports Strong Galaxy Sales" | SSNLF | EARNINGS_BEAT | B |
| 3 | "AMD Gains Server Market Share from Intel" | AMD, INTC | POSITIVE_SENTIMENT | A |
| 4 | "Tesla Cuts Prices Again in China" | TSLA | NEGATIVE_SENTIMENT | B |
| 5 | "Rivian Delays R2 Production" | RIVN | GUIDANCE_CUT | C |
| 6 | "Fed Holds Rates Steady, Signals Future Cuts" | SPY, QQQ | CENTRAL_BANK | B |
| 7 | "TSMC Warns of Chip Demand Slowdown" | TSM | GUIDANCE_CUT | A |
| 8 | "Nvidia Unveils New AI Chip at GTC" | NVDA | PRODUCT_LAUNCH | A |
| 9 | "Intel Struggles with Foundry Business" | INTC | NEGATIVE_SENTIMENT | B |
| 10 | "Amazon AWS Growth Beats Cloud Rivals" | AMZN | EARNINGS_BEAT | B |
| 11 | "Microsoft Copilot Adoption Accelerates" | MSFT | POSITIVE_SENTIMENT | A |
| 12 | "Google Antitrust Ruling Impact" | GOOGL | LEGAL_RULING | B |
| 13 | "Semiconductor Equipment Orders Decline" | ASML, AMAT | NEGATIVE_SENTIMENT | C |
| 14 | "EV Battery Supply Chain Tightens" | (multiple) | MACRO_DATA | C |
| 15 | "Tech Layoffs Continue Across Sector" | (sector) | NEGATIVE_SENTIMENT | B |

**Graph Setup (in addition to LLM extraction)**:
- PEER_OF relationships: AAPL↔SSNLF, AMD↔INTC, TSLA↔RIVN, NVDA↔AMD
- CONSTITUENT_OF: AAPL→SPY, NVDA→QQQ, etc.
- SECTOR: All tech stocks → Technology sector

### Expected Outcomes

1. **Quantifiable Improvement**: Hybrid queries should show:
   - 20-40% more relevant results vs semantic-only
   - 30-50% better recall on peer-related content
   - Lateral discoveries that pure semantic cannot make

2. **Use Case Validation**:
   - Portfolio manager asking "What affects my AAPL position?" gets peer news
   - Macro analyst asking "Fed impact" sees cascading effects on sectors
   - Quant researcher finds pattern matches via event types

3. **Architecture Validation**:
   - Ingestion correctly populates both indexes
   - Query service properly combines both result sets
   - Group permissions enforced across both systems

### Deliverables

1. `test/test_integration_hybrid_query.py` - Full integration test suite
2. Updated `app/services/query_service.py` - Graph-expanded retrieval
3. Metrics report documenting hybrid vs semantic-only performance
4. `docs/IMPLEMENTATION_STATUS.md` update with Phase 8 completion

