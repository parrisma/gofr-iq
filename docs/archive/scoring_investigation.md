# Scoring Quality Investigation: Bias Sweep Results & Systematic Improvement Plan

## 1. Executive Summary

The simulation pipeline has been successfully executed end-to-end, including ingestion of 1000 baseline documents, 4 Phase3 scenarios, and 11 Phase4 scenarios. The final bias sweep reveals significant scoring deficiencies:

1.  **AlphaScore is 0.0 across all simulations.** The system currently fails to surface *any* relevant "discovery" content (articles not about already-held tickers) in the top-3 results.
2.  **Vector/Thematic channels are overpowered by Graph signals.** `DIRECT_HOLDING` candidates (score ~1.0) mathematically dominate all other signals, creating an echo chamber.
3.  **Vector activation bug.** A threshold logic error (`vector_activation_threshold=0.5`) completely disables vector search for lambda <= 0.5, rendering the "Defense" and "Balanced" profiles identical and blind to semantic matches.
4.  **Recall is stagnant.** Phase3 Recall@10 is stuck at ~14% and Phase4 M-series (mandate needles) at ~30%, confirming that the system struggles to find content that isn't explicitly ticker-linked.

This document captures the detailed results and proposes a systematic investigation to refine scoring to an operational baseline.

## 2. Bias Sweep Results (Run: `2024-10-24`)

| Metric | Lambda=0.0 (Defense) | Lambda=0.25 | Lambda=0.5 (Balanced) | Lambda=0.75 | Lambda=1.0 (Alpha) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **AlphaScore** | **0.00** 🔴 | **0.00** 🔴 | **0.00** 🔴 | **0.00** 🔴 | **0.00** 🔴 |
| Avg Articles | ~88 | ~88 | ~95 | ~105 | ~120 |
| Zero Returns | 0/27 | 0/27 | 0/27 | 0/27 | 0/27 |
| **Phase3 Recall@10** | 0.143 | 0.143 | 0.143 | 0.143 | 0.143 |
| **Phase4 Recall@10** | 0.292 | 0.292 | 0.312 | 0.315 | 0.354 |
| P4 Mandate (M*) | 0.333 | 0.333 | 0.350 | 0.380 | 0.420 |
| P4 Rel-Hop (R*) | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

### Key Observations
*   **Identical Performance at Low Lambda:** Lambda 0.0 and 0.25 produce identical recall metrics, strongly suggesting the "slider" is broken at the low end.
*   **AlphaScore Zero:** We are *never* showing a top-3 article that isn't about a held position. The "Discovery" promise of the product is currently unmet.
*   **Relationship Hops Failed:** Phase4 R-series (relationship hops) recall is 0.000. Second-order graph traversal (Supplier/Competitor) is either not triggering or scoring too low.

## 3. Root Cause Analysis

### 3.1. The "Echo Chamber" Formula (Why AlphaScore is 0)

AlphaScore measures the proportion of top-3 articles that *do not* overlap with client positions.
Current Scoring Logic (`query_service.py`):

*   **Direct Holding:** `base_score = 1.0 - (0.4 * lambda)`
    *   At lambda=1.0 (Alpha mode), score = 0.6 + potential boosts.
    *   At lambda=0.0 (Defense mode), score = 1.0.
*   **Vector/Thematic:** `base_score` maxes out at ~0.5 - 0.8 depending on lambda.
*   **The Problem:** A `DIRECT_HOLDING` hit almost always scores higher than a perfect `VECTOR` or `THEMATIC` hit.
*   **Result:** The top of the feed is filled with updates on what the client already owns. "Discovery" items are pushed to positions 10-20, invisible to the AlphaScore metric (which only checks Top 3).

### 3.2. Vector Activation Bug (The "Dead Zone")

In `query_service.py`:
```python
if self.embedding_index and scoring.opportunity_bias > scoring.vector_activation_threshold:
    # ... search vector index ...
```
`ScoringConfig` sets `vector_activation_threshold = 0.5` (default).
*   **Effect:** For lambda=0.0 and lambda=0.25, **vector search is never executed.**
*   **Consequence:** "Defense" and "Conservative" profiles miss all semantic signals (e.g., "Yield Curve Inversion" impacting a Fixed Income mandate), relying 100% on graph links.

### 3.3. Phase4 Needle Failure

*   **Mandate Needles (M1-M6):** These documents mention relevant concepts (e.g., "Generative AI") but not client tickers. They rely on `VECTOR` or `THEMATIC` channels.
    *   Because `DIRECT_HOLDING` candidates dominate the score, these needles are buried by noise from the 1000-document baseline (likely random noise about held tickers).
*   **Relationship Hops (R1-R3):** `COMPETITOR` / `SUPPLY_CHAIN` logic exists but appears weak (`base=0.4` to `0.6`). If a client holds NVDA, a supplier story about TSMC scores ~0.5, while a direct story about NVDA scores 1.0. The direct story always wins.

## 4. Proposed Systematic Investigation

We need to operationalize the scoring logic. I propose a 3-step investigation plan.

### Step 1: Fix the Mechanics (The "Plumbing")
*   **Objective:** Ensure all signal channels actually fire when intended.
*   **Actions:**
    1.  **Lower `vector_activation_threshold`:** Change default from 0.5 to 0.0 or 0.1. A "Defense" client still needs semantic warning signals.
    2.  **Fix Lambda Interpolation:** Verify `ScoringConfig.from_opportunity_bias` produces distinct weights for 0.0 vs 0.25.
    3.  **Debug Relationship Hops:** Verify `_expand_lateral_tickers` is actually finding peers/suppliers in the graph.

### Step 2: Rebalance the Equation (The "Tuning")
*   **Objective:** Allow a perfect "Discovery" hit to beat a mediocre "Holding" hit.
*   **Actions:**
    1.  **Cap Direct Holding Score:** Reduce `direct_holding_base` to ~0.7 max? Or boost `thematic`/`vector` bases?
    2.  **Implement "Discovery Boost":** Explicitly boost score for items *not* in holdings if they have high thematic/vector relevance.
    3.  **Sort Logic:** Consider ensuring at least 1 "Discovery" item in Top 3 if it crosses a quality threshold (forcing diversity).

### Step 3: Validation Protocol
*   **Metric:** Retest against bias sweep.
*   **Success Criteria:**
    *   AlphaScore > 0.3 for Lambda=1.0 (at least 1 in 3 articles is discovery).
    *   AlphaScore ≈ 0.0 for Lambda=0.0 (Defense should focus on holdings).
    *   Phase4 Recall > 0.8 (Needles must be found).

## 5. Immediate Action Plan

1.  **Create `docs/scoring_fix_implementation_plan.md`:** Detail the code changes for Step 1 & 2.
2.  **Execute Fixes:** Modify `query_service.py` and `app/config.py`.
3.  **Re-run Bias Sweep:** Verify metrics improvement without full re-ingestion (scoring is query-time).

This approach moves us from "running the simulation" to "fixing the product logic" based on the simulation's findings.
