# Specification: Top Client News Algorithm (Target State)

**Date**: 2026-02-21
**Version**: 3.0 (Target State - Maximal Leverage)
**Owner**: Sales Trading / Data Science
**Status**: Specification

## Executive Summary

This document specifies the target state for the `get_top_client_news` algorithm. The goal is to evolve the system from a static "Portfolio Monitor" into a dynamic **"Alpha Intelligence Engine"** that maximizes relevance by fully leveraging the interplay between Graph (Structure), Vector (Nuance), and LLM (Context).

The core innovation is the **"Relevance Surface"**, a multi-dimensional scoring plane that dynamically re-weights signals based on a user-controlled **`opportunity_bias` ($\lambda$)**, shifting the system from "Defense" (Portfolio Protection) to "Offense" (Alpha Generation).

## 1. Core Principles

1.  **Relevance involves Structure & Semantic**: Structure (Graph) proves *why* something matters (e.g., "Supplier of key holding"). Semantic (Vector) proves *what* matters (e.g., "Soft thematic match for 'Generative AI' in mandate").
2.  **Tunable Bias**: One algorithm serves multiple personas (Risk Manager vs. Idea Generator) via a single tunable parameter ($\lambda$).
3.  **Time is Exponential**: Breaking news (minutes old) is exponentially more valuable than stale news (hours old).
4.  **Influence Accumulates**: A story affecting *three* portfolio companies via supply chain is more critical than a story affecting *one*.

## 2. Logic Flow & Scoring Model

### 2.1 Context Resolution (Inputs)
The algorithm begins by building a comprehensive profile of the client from the Knowledge Graph:

*   **Holdings**: Tickers and their % weight in the portfolio.
*   **Watchlist**: Tickers explicitly tracked by the client.
*   **Benchmark**: The reference index ticker.
*   **Mandate Themes**: Structured concepts (e.g., "AI", "Semiconductor") extracted from the client's investment mandate text.
*   **Mandate Embedding**: A dense vector representation of the *entire* mandate text (for soft matching).
*   **Restrictions**: ESG/Sector exclusions (Hard Constraint).

### 2.2 Candidate Generation (Hybrid Retrieval)

We generate candidates using two parallel retrieval strategies that are merged:

#### A. Structured Graph Retrieval (The "Known Knowns")
Query pathways in Neo4j: `(Document)-[:AFFECTS]->(Entity)-[:RELATED_TO*1..2]->(Client)`.
*   **Direct**: News on Holdings/Watchlist.
*   **Lateral**: News on Competitors, Suppliers, Partners, Peers.
*   **Thematic**: News on explicitly tagged Themes matching Mandate Themes.

#### B. Semantic Vector Retrieval (The "Unknown Knowns")
Query ChromaDB using the **Mandate Embedding**:
*   Retrieve documents with high cosine similarity (>0.75) to the mandate text.
*   **Crucial Step**: This captures nuanced interest (e.g., "emerging battery tech") that lacks a rigid graph tag.

### 2.3 Dynamic Base Scoring ($\lambda$)

The **Base Score** for each path is determined dynamically by the **Opportunity Bias ($\lambda \in [0.0, 1.0]$)**.

| Signal Category | Retrieval Source | Base Score Formula | $\lambda=0.0$ (Defense) | $\lambda=1.0$ (Offense) |
| :--- | :--- | :--- | :--- | :--- |
| **Direct Holding** | Graph | $1.0 - (0.4 \times \lambda)$ | **1.00** | 0.60 |
| **Watchlist** | Graph | Fixed | 0.80 | 0.80 |
| **Thematic Match** | Graph | $0.5 + (0.5 \times \lambda)$ | 0.50 | **1.00** |
| **Vector Similarity** | Vector | $0.4 + (0.4 \times \lambda)$ | 0.40 | 0.80 |
| **Lateral (Comp/Supply)** | Graph | $0.4 + (0.4 \times \lambda)$ | 0.40 | 0.80 |

### 2.4 Advanced Boosts (The "Alpha" Factors)

After base scoring, we apply targeted boosts to capture nuance.

#### A. Influence Accumulation (Graph Power)
We boost documents that affect *multiple* parts of the portfolio.
$$ B_{influence} = 0.1 \times (\text{distinct\_paths} - 1) $$
*   *Example*: A chip shortage story affects holding NVDA (Direct) AND holding MSFT (Supplier).
    *   Base Score: 1.0 (Direct)
    *   Boost: +0.1 (2 paths)
    *   **Result**: 1.1 (Super-critical)

#### B. Non-Linear Position Conviction
We award a logarithmic boost to top concentrations.
$$ B_{pos} = 0.3 \times \frac{\log(1 + rank\_percentile)}{\log(2)} $$
*   **Top 5 Positions**: +0.30
*   **Tail**: +0.05

#### C. Mandate-Specific Event Types
We boost specific events that match the *nature* of the fund.
*   **Risk Arb / Multi-Strat**: +0.15 for `M_AND_A`, `SPINOFF`, `IPO`.
*   **Income**: +0.10 for `DIVIDEND`, `BUYBACK`.

### 2.5 Hybrid Scoring Equation

The final relevance score for a document is calculated as:

$$
Score = (W_{structure} \times S_{hybrid}) + (W_{impact} \times S_{impact}) + (W_{recency} \times S_{recency})
$$

Where:
*   $S_{hybrid} = \text{max}(\text{GraphScore}, \text{VectorScore}) + B_{influence} + B_{pos} + B_{event}$
*   $S_{impact} = \text{Normalized Impact Score } (0.0 - 1.0)$
*   $S_{recency} = e^{-\ln(2) \cdot \frac{age\_mins}{60}}$ (Half-life: 60 mins)

**Recency Behavior**:
A story that is **0 minutes old** gets a full weighted score. A story that is **4 hours old** gets **~6%** of the recency weight. This creates a "breaking news" ticker effect.

### 2.6 Filters
*   **Hard Exclusions**: Any document tagging a Company or Sector in the Client's restriction list is dropped immediately.
*   **Time Window**: Pre-filter at 24 hours to constrain query, ranking handled by decay.

## 3. Implementation Plan

### Phase 1: Data Foundations
1.  **Thematic Ingestion**: Ensure `MandateEnrichmentService` is reliably tagging Client Profiles with themes.
2.  **Mandate Embedding**: Generate and store vector embeddings of `ClientProfile.mandate_text`.

### Phase 2: Query Service Upgrade
1.  Update `get_top_client_news` to accept `opportunity_bias`.
2.  Implement **Hybrid Retrieval**: Parallel execution of Neo4j (Graph) and ChromaDB (Vector).
3.  Implement **Path Accumulation**: Use Cypher `REDUCE` or Python-side aggregation to count distinct paths for influence boosting.
4.  Implement Scoring Formula.

### Phase 3: User Control
1.  Expose the `offense/defense` slider in the UI.
2.  Default to `0.0` (Defense) for standard "Holdings" view.
3.  Default to `0.8` (Offense) for "Idea Generation" view.

## 4. Technical Architecture Enhancements (Graph, Vector, GenAI)

### 4.1 Vector Database (ChromaDB) - "Soft Thematic Matching"
*   **Role**: Captures the "Unknown Knowns".
*   **Mechanism**: Embed client mandate text. Search against news.
*   **Value**: Finds stories relevant to the *concept* of the mandate even if explicit tags are missing.

### 4.2 Graph Database (Neo4j) - "Influence Propagation"
*   **Role**: Captures the "Systemic Impact".
*   **Mechanism**: Variable-length path queries with accumulation.
*   **Value**: Automatically identifies "Keystone" events that ripple through multiple portfolio holdings.

### 4.3 Prompt Engineering (LLM) - "Contextual Synthesis"
*   **Role**: Delivers the "Why".
*   **Mechanism**: Dynamic system prompt injection based on `opportunity_bias`.
    *   *Defense*: "Highlight downside risks to holdings X, Y, Z."
    *   *Offense*: "Highlight growth opportunity in sector A similar to holding B."
*   **Value**: Ensures the *explanation* matches the *reason* for selection.

### 4.4 Entity Alias Resolution - "One Entity, Many Names"
*   **Role**: Ensures instruments and clients are reliably matched regardless of which identifier appears in source data.
*   **Problem**: A news article may reference "Alphabet", "Google", "GOOG", "GOOG.O" (RIC), or US02079K3059 (ISIN). Today the graph keys on a single `ticker`, so non-ticker references create orphan nodes or miss matches entirely. Similarly, clients may be referenced by Salesforce Account ID, Bloomberg FIRM code, legal name, or desk alias.
*   **Mechanism**: `Alias` node pattern in Neo4j.
    *   Each canonical entity (Instrument or Client) has zero or more `(:Alias {value, scheme})` nodes connected via `HAS_ALIAS`.
    *   `scheme` for instruments: `TICKER`, `RIC`, `SEDOL`, `ISIN`, `CUSIP`, `FIGI`, `NAME_VARIANT`.
    *   `scheme` for clients: `SFDC`, `BBG_FIRM`, `LEGAL_NAME`, `DESK_ALIAS`.
    *   Uniqueness constraint on `(scheme, value)` ensures O(1) lookups.
*   **`AliasResolver` service**: `resolve(value, scheme=None) -> canonical_guid`. Called during ingestion before creating `AFFECTS`/`MENTIONS` relationships so that "Alphabet" in news text resolves to the canonical `GOOGL` Instrument node.
*   **Value**: Eliminates duplicate entity nodes, increases recall on graph-based candidate retrieval, and enables external system integration (Salesforce, Bloomberg) without manual GUID mapping.

### 4.5 Index Rebalance & Benchmark Composition - "Forced Flow Detection"
*   **Role**: Detects index add/delete/rebalance events that create forced passive flow and tracking error for benchmark-sensitive clients.
*   **Problem**: Event types `INDEX_ADD`, `INDEX_DELETE`, `INDEX_REBAL` are extracted at ingestion, and the graph schema defines `CONSTITUENT_OF` (Instrument -> Index) and `BENCHMARKED_TO` (ClientProfile -> Index). However, `CONSTITUENT_OF` is never populated, and the scoring layer treats benchmark news identically to generic watchlist items. A stock entering or leaving a client's benchmark is a forced-flow event that should rank near the top -- not sit at watchlist base score 0.8.
*   **Mechanism**:
    *   Populate and maintain `CONSTITUENT_OF` relationships with weights so the graph connects index events to client benchmarks.
    *   Store benchmark constituent weights alongside portfolio weights to enable **active weight** calculation: $w_{active} = w_{portfolio} - w_{benchmark}$.
    *   Add a **Benchmark Event Boost** in the scoring model:
        *   If a document's `event_type` is `INDEX_ADD` or `INDEX_DELETE` AND the affected instrument is a constituent of (or being added to / removed from) the client's benchmark:
        *   $B_{benchmark} = 0.3$ for `INDEX_ADD`/`INDEX_DELETE`, $0.15$ for `INDEX_REBAL`.
        *   Scale by absolute active weight: larger active weight deviation = higher urgency.
*   **Value**: Passive managers get immediate signal on forced rebalance trades. Active managers see tracking error alerts. Both get differentiated scoring instead of generic watchlist noise.

### 4.6 Duplicate Detection - "One Event, Many Wires"
*   **Role**: Prevents the same market event from flooding a client's feed with near-identical stories from multiple sources.
*   **Problem**: A single event (e.g., AAPL earnings beat) generates stories from Reuters, Bloomberg, Dow Jones, and multiple financial blogs within minutes. The current detector uses in-memory bag-of-words cosine at threshold 0.95, which only catches near-verbatim copies. Paraphrased coverage of the same event (typical wire behavior) scores 0.70-0.90 and slips through. The in-memory index is also lost on restart.
*   **Mechanism** (multi-layer):
    1.  **Content Hash** (exact): SHA-256 of normalized text. Catches verbatim reposts. Persisted as a property on the Document node in Neo4j with a lookup index (no in-memory rebuild needed).
    2.  **Entity+Event Fingerprint** (structural): `hash(sorted(affected_tickers) + event_type + date)`. Two documents sharing the same fingerprint within 24 hours are near-certain duplicates regardless of wording. O(1) dict/index lookup.
    3.  **Vector Similarity** (semantic): Query ChromaDB for documents with cosine similarity > 0.85 within a 48-hour temporal window. Catches paraphrased multi-source coverage and cross-language duplicates (the embedding model is language-agnostic).
*   **Behavior**: Duplicates are still stored (append-only) but flagged with `duplicate_of` and `duplicate_score`. The scoring layer in `get_top_client_news` should suppress flagged duplicates or collapse them into a single item with a "also reported by N sources" annotation.
*   **Value**: A client's Top 3 feed shows 3 distinct events, not the same AAPL earnings story from 3 wires.

