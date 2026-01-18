# GOFR-IQ Simulation - Architecture & Design

**Purpose**: Conceptual overview of the simulation environment, data models, and system components.

**Companion docs**: [simulation/OPERATIONAL_GUIDE.md](simulation/OPERATIONAL_GUIDE.md), [simulation/VALIDATION.md](simulation/VALIDATION.md)

---

## 1. System Objective

The simulation environment generates a self-contained "pocket universe" of financial data to validate GOFR-IQ's core value proposition: **Intelligent Profile-based Selection (IPS)**.

**Primary Goal**: Prove that the system can route relevant information to the right client based on their holdings, mandate, and trust preferences, while filtering out noise.

**Validation Strategy**:
- Create a known universe (companies, relationships, portfolios)
- Inject synthetic "ground truth" events with known relevance
- Verify if the system correctly routes these events to affected clients
- Measure precision (low noise) and recall (no missed signals)

### Platform Stack (Runtime Targets)
- **Graph**: Neo4j (company, instrument, factor, client, document nodes)
- **Vector Store**: ChromaDB (document chunks + metadata)
- **Policy Input**: IPS JSON profiles supplied at query time
- **Orchestration**: `run_simulation.sh` stage-gates the pipeline (reset → load → generate → ingest → validate)
- **LLM**: Claude via OpenRouter for story generation and entity extraction

---

## 2. Universe Model

The simulation models a minimal viable financial ecosystem:

### 2.1 Companies & Instruments
- **16 Synthetic Companies**: Fictional entities across 4 sectors (Technology, Energy, Healthcare, Finance)
- **Relationships**:
  - `SUPPLIES_TO`: Material dependencies (e.g., OmniCorp chips -> QuantumTech servers)
  - `COMPETES_WITH`: Market rivalry (e.g., GreenEnergy vs FossilCorp)
  - `PARTNER_OF`: Strategic alliances
- **Instruments**:
  - Equity (Common Stock)
  - Debt (Bonds)
  - Derivatives (Options/Futures)

### 2.2 Macro Factors
- **5 Key Factors**: Interest Rates, Commodity Prices, Geopolitical Risk, Regulation, Tech Innovation
- **Exposures**: Every company has `EXPOSED_TO` relationships with beta values measuring sensitivity (e.g., BankOne has -0.8 beta to Interest Rates)

---

## 3. Client Model

We simulate three distinct client archetypes to test different filtering logics:

### 3.1 Hedge Fund ("Alpha Seekers")
- **Profile**: High risk tolerance, aggressive turnover
- **Portfolio**: Concentrated positions in Tech and Energy
- **IPS Policy**:
  - **Trust Level**: Low (accepts rumors/noise if actionable)
  - **Relevance**: High (supply chain shocks, competitor moves)
  - **Filtering**: Minimal (wants raw feed)

### 3.2 Pension Fund ("Stability First")
- **Profile**: Long-term horizon, conservation of capital
- **Portfolio**: Diversified blue-chips, heavy Fixed Income
- **IPS Policy**:
  - **Trust Level**: High (only confirmed news from Tier-1 sources)
  - **Relevance**: Strategic (regulatory changes, macro shifts)
  - **Filtering**: Aggressive (no noise, no rumors)

### 3.3 Retail Trader ("Trend Follower")
- **Profile**: Momentum-based, short-term
- **Portfolio**: High-volatility names (Meme stocks, Tech)
- **IPS Policy**:
  - **Trust Level**: Medium (accepts some speculation)
  - **Relevance**: Sentiment (social buzz, earnings surprises)
  - **Filtering**: Moderate

---

## 4. Graph Schema

The Neo4j graph connects the universe with ingested content:

```mermaid
graph TD
    DOC[Document] -->|MENTIONS| CO[Company]
    DOC -->|AFFECTS {magnitude, confidence}| INS[Instrument]
    CO -->|ISSUES| INS
    CO -->|SUPPLIES_TO| CO2[Company]
    CO -->|COMPETES_WITH| CO3[Company]
    CLI[Client] -->|HOLDS {weight}| INS
    CLI -->|WATCHES| INS
    CLI -->|SENSITIVE_TO| FAC[Factor]
    CO -->|EXPOSED_TO {beta}| FAC
```

### Key Relationships
- **Direct Impact**: Document explicitly Mentions an Instrument
- **Indirect Impact**: Document affects a Supplier/Competitor of a Held Instrument
- **Factor Impact**: Document changes a Factor (e.g., "Fed hikes rates") which affects Exposed Companies

---

## 4. Component Map

- **UniverseBuilder** (`simulation/universe/builder.py`): Constructs companies, instruments, factors, and relationships.
- **load_simulation_data.py**: Loads the universe (companies, instruments, clients, relationships) into Neo4j; replaces legacy loaders.
- **generate_synthetic_stories.py**: Creates ground-truth stories with validation metadata; supports caching to avoid repeat LLM calls.
- **ingest_synthetic_stories.py**: Writes documents into Neo4j, chunks + embeds to ChromaDB, extracts entities/relationships.
- **client_profiler.py**: Applies IPS JSON profiles at query time (min trust, sector filters, watchlists, exclusions).
- **query_client_feed.py**: Orchestrates graph + vector search via MCP tools to assemble ranked feeds per client.
- **demo_ips_filtering.py**: Side-by-side IPS filtering demo across client archetypes.
- **validate_feeds.py**: Automated harness measuring recall/precision against ground-truth metadata.

---

## 5. IPS Architecture

The **Intelligent Profile-based Selection (IPS)** engine is the brain of GOFR-IQ.

### 5.1 Workflow
1.  **Ingestion**: Documents are ingested, vectorized (ChromaDB), and linked to graph (Neo4j).
2.  **Profiling**: `ClientProfiler` loads client's IPS policy (JSON).
3.  **Discovery**:
    *   **Direct**: Find news on held instruments.
    *   **Graph**: Traverse 1-2 hops (Supply Chain, Competitors).
    *   **Vector**: Find semantically similar content to mandate themes.
4.  **Filtering**:
    *   **Trust Filter**: Reject sources below `min_trust_score`.
    *   **Entity Filter**: Apply `whitelist`/`blacklist` rules.
    *   **Sector Filter**: Exclude restricted sectors (ESG).
5.  **Scoring & Ranking**:
    *   Synthesize Relevance Score (0-100) based on graph distance and semantic match.
    *   Prioritize High Impact / High Confidence signals.

### 5.2 External Policy Injection
IPS profiles are **not** stored in the graph. They are supplied as JSON objects at query time (runtime).
- **Why?**: Allows dynamic modeling, hypothetical scenarios, and strict data privacy (client distinct from data).
- **Format**: See `client_ips/` for examples.

---

## 6. Story Generation (Synthetic Ground Truth)

We use LLMs (Claude 3.5 Sonnet) to create high-quality synthetic financial news.

### 6.1 Generation Logic
- **Prompt Engineering**: We feed the "state of the universe" (companies, relationships) to the LLM.
- **Scenario Injection**: "Create a supply chain disruption between OmniCorp and QuantumTech."
- **Metadata Tagging**: The LLM outputs JSON with:
    *   `title`, `content`
    *   `ground_truth_impact`: Which instruments *should* move.
    *   `expected_relevance`: Why it matters (Direct, Supplier, Competitor).
  *   `validation_metadata`: Scenario, base ticker, expected clients, hops, expected rank range.

### 6.2 Validation Harness
Because we generated the stories, we know the "Right Answer."
- **Test**: Did the Hedge Fund see the OmniCorp story?
- **Expected**: YES (holds QuantumTech, who buys from OmniCorp).
- **Result**: PASS/FAIL based on feed inclusion.

### 6.3 Caching Strategy
- Stories are cached under `simulation/test_output/` and reused across runs when titles match.
- Reduces OpenRouter spend and speeds up large-batch simulations.

---

## 7. Feed Intelligence

How we find "Hidden Alpha":

### 7.1 Second-Order Effects
- **Scenario**: "Factory fire at OmniCorp."
- **Direct**: Bad for OmniCorp stock.
- **Second-Order**: Bad for QuantumTech (can't build servers).
- **Third-Order**: Good for ServerSys (competitor to QuantumTech).
- **Graph Traversal**: IPS engine hops `(OmniCorp)-[:SUPPLIES_TO]->(QuantumTech)<-[:COMPETES_WITH]-(ServerSys)` to surface this news to a ServerSys holder.

### 7.2 Semantic Expansion
- **Scenario**: "Lithium shortage looming."
- **Graph**: May not explicitly link "Lithium" to "GreenEnergy Corp."
- **Vector Search**: Embeddings associate "Lithium" with "Batteries" and "EVs."
- **Result**: News surfaced to GreenEnergy holders via semantic similarity.

---

## 8. Data Flow Summary

1.  **Load Universe**: `load_simulation_data.py` populates Neo4j with companies, instruments, factors, clients, relationships.
2.  **Generate**: `generate_synthetic_stories.py` produces JSON stories with validation metadata (uses cache when available).
3.  **Ingest**: `ingest_synthetic_stories.py` writes to Neo4j + ChromaDB and builds entity/relationship edges.
4.  **Profile**: `ClientProfiler` reads `client_ips/*.json` at query time (no persistence in graph).
5.  **Query**: `query_client_feed.py` calls MCP tools to combine graph traversal + vector search.
6.  **Result**: Ranked, IPS-filtered feed per client archetype.
7.  **Validate**: `validate_feeds.py` compares outputs to ground-truth expectations.

---

**Last Updated**: 2026-01-18  
**Version**: Post-consolidation v1.0
