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

**Objective**: Verify the entire pipeline from ingestion to client-specific retrieval.

### Tasks
1.  **Test Data**: Create a set of synthetic news articles (Earnings beat, M&A rumor, Macro event).
2.  **Test Personas**: Define 3 client profiles (Hedge Fund, Long-Only, Quant) in the test setup.
3.  **Integration Test Suite** (`test/test_integration_graph_ranking.py`):
    *   **Step 1**: Ingest articles (mocking LLM extraction or using a deterministic fake).
    *   **Step 2**: Verify Graph State (Nodes and relationships created correctly).
    *   **Step 3**: Query as Hedge Fund -> Expect high volatility/recent news.
    *   **Step 4**: Query as Long-Only -> Expect fundamental/major news.
    *   **Step 5**: Verify permissioning (Client A cannot see Client B's feed).

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
