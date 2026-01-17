# Simulation Objective: Client-Centric Retrieval-Augmented Story Selection

## Core Mission
The primary objective of the GOFR-IQ Simulation framework is to validate and enhance the platform's ability to **ingest and semantically index unstructured narrative data to enable Client-Centric Retrieval-Augmented Story Selection.**

## Formal System Definition
GOFR-IQ functions as a specialized semantic ingestion engine that transforms disparate financial narratives into a unified **hybrid knowledge graph and vector space**. This structured substrate is designed specifically to support high-precision retrieval algorithms that dynamically filter, rank, and contextualize stories based on individual **client asset portfolios** and **investment mandates**, thereby bridging the gap between raw information flow and personalized client intelligence.

## Simulation Goals
This simulation environment serves as the primary proving ground for these capabilities. We use synthetic data generation and automated scenarios to:

1.  **Prove Retrieval Precision**: Verify that a "Client" with a specific portfolio (e.g., Long AAPL, Short TSLA) receives *only* the stories relevant to those positions or their related ecosystem/competitors.
2.  **Validate Ranking Logic**: Ensure that "High Impact" stories (Tier 1/Platinum) bubble to the top of a client's feed compared to noise (Tier 3/Bronze).
3.  **Stress Test Ingestion**: Confirm the system handles multi-lingual, high-velocity ingestion without degrading query performance.
4.  **Enhance Graph Traversal**: Refine the graph queries to ensure "second-degree" relevance (e.g., a supplier to a portfolio holding) is correctly identified and surfaced.

## Key Definitions

*   **Inject Stories**: The *Ingestion Pipeline* mechanisms that normalize multi-lingual text into immutable `Document` nodes and vector embeddings.
*   **Client Focused**: The utilization of *Graph Relations* (e.g., `(Client)-[:HAS_HOLDING]->(Instrument)`) to strictly scope relevance to user needs.
*   **Retrieval Augmented Story Selection**: The *Query Service's* ability to use those relations to retrieve only the "signals" that matter to a specific "receiver", filtering out noise via semantic similarity and impact scoring.

## Architectural Alignment
The current GOFR-IQ architecture (referencing `docs/architecture/overview.md` and `docs/architecture/graph-design.md`) creates the structural foundation required to meet these objectives:

### 1. Client-Centricity via Graph Topology
The graph schema explicitly models the "Receiver" of intelligence through the **Client Node Integration**:
-   **Direct Exposure**: `(Client)-[:HAS_PORTFOLIO]->(Portfolio)-[:HOLDS]->(Instrument)`
-   **Indirect Relevance**: `(Instrument)-[:ISSUED_BY]->(Company)-[:PEER_OF]->(Company)` (Sector/Peer correlation)
-   **Impact Propagation**: Stories are linked via `(Document)-[:AFFECTS {magnitude, direction}]->(Instrument)`, allowing traversal from News -> Instrument -> Portfolio -> Client.

### 2. Retrieval-Augmented Selection (RAS)
The Query Service implements RAS rather than simple keyword search by:
-   **Vector Space**: Embedding documents into ChromaDB to find "semantically similar" narratives even without exact keyword matches.
-   **Graph Traversal**: Using Cypher queries to "walk" from a Client's portfolio to relevant documents.
-   **Hybrid Scoring**: The final rank is a weighted function of:
    -   `Vector Similarity` (Content relevance)
    -   `Graph Distance` (How many hops from the portfolio?)
    -   `Impact Score` (LLM-derived significance)
    -   `Recency` (Time decay)

### 3. Simulation-Ready Infrastructure
The system is built for simulation verification:
-   **Modular Ingestion**: The `IngestService` decouples source data from processing, allowing the `simulation/` scripts to inject synthetic "perfect storms" or specific market scenarios.
-   **Deterministic Scoring**: The explicit impact tiers (Platinum/Gold/Silver/Bronze) allow unit-testable assertions about feed ordering.
-   **Isolation**: Group-based access control (`:IN_GROUP`) ensures simulation data does not bleed into production contexts.
