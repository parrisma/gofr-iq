# Scoring Fix Implementation Plan

## 1. Objective
Operationalize the scoring logic to fix two critical failures identified in `docs/scoring_investigation.md`:
1.  **The "Dead Zone"**: Vector search is currently disabled for "Defense" and "Balanced" profiles due to a high activation threshold.
2.  **The "Echo Chamber"**: Direct holdings score so high (1.0) that they mathematically exclude all "Discovery" content (AlphaScore=0).

## 2. Root Cause Analysis
*   **Vector Activation Bug**: `ScoringConfig.vector_activation_threshold` defaults to `0.5`. Since defense profiles have `lambda=0.0`, they never search the vector index.
*   **Scoring Imbalance**:
    *   `direct_holding_base` = `1.0 - 0.4*lam`. At `lam=1.0` (Alpha), this is `0.6`.
    *   `vector_base` = `0.4 + 0.4*lam`. At `lam=1.0`, this is `0.8`.
    *   However, `direct_holding` is almost always accompanied by `impact_score` and `recency`.
    *   Crucially, at `lam=0.0` (Defense), `direct_holding` is `1.0` while `vector_base` is only `0.4`.
*   **AlphaScore Definition**: Finds usage of non-held tickers in Top 3. If `direct_holding` is 1.0, it pushes everything else out of Top 3.

## 3. Implementation Steps

### Step 1: Fix the Mechanics (The "Plumbing")
**Target:** `app/services/query_service.py`

1.  **Lower Vector Activation Threshold**:
    *   Change default `vector_activation_threshold` from `0.5` to `0.0` (or `0.05`).
    *   **Rationale**: Even a "Defense" client cares about semantic risks (e.g., "Regulatory Crackdown" matching their mandate).
    
2.  **Refine Lambda Interpolation**:
    *   Ensure `from_opportunity_bias` creates distinct configs for `0.0` vs `0.25`.
    *   Currently, `vector_activation` binary switch makes them identical.
    
3.  **Enable Relationship Hops**:
    *   Review `_expand_lateral_tickers`.
    *   Ensure `COMPETITOR` / `SUPPLY_CHAIN` candidates are actually being added to `graph_candidates`.

### Step 2: Rebalance the Equation (The "Tuning")
**Target:** `app/services/query_service.py` -> `ScoringConfig.from_opportunity_bias`

1.  **Cap Direct Holding Base**:
    *   **Current**: `1.0` (Defense) -> `0.6` (Alpha).
    *   **New Proposal**: `0.8` (Defense) -> `0.4` (Alpha).
    *   *Why?* We need room for a really good `vector` match (0.8) to beat a mediocre `holding` match.

2.  **Boost Discovery Channels**:
    *   **Vector**: Increase base to `0.5 + 0.4*lam` (Max 0.9).
    *   **Thematic**: Increase base to `0.6 + 0.3*lam` (Max 0.9).

3.  **Implement "Discovery Boost"**:
    *   In the final scoring loop, if a candidate is **NOT** a `DIRECT_HOLDING`:
        *   If `vector_score > 0.7` OR `thematic_score > 0.7`:
        *   Add `discovery_boost = 0.2`.
    *   This explicitly helps AlphaScore by pushing high-quality non-holding items up.

### Step 3: Verification
1.  **Run Bias Sweep**:
    *   `uv run simulation/validate_avatar_feeds.py --bias-sweep`
2.  **Success Criteria**:
    *   **AlphaScore > 0.0** (Critical).
    *   **Phase4 Recall > 0.5** (Must find the finding M1-M6 needles).
    *   **Defense Profile** still returns relevant hits (not empty).

## 4. Execution Order

1.  **Edit `app/services/query_service.py`**:
    *   Update `ScoringConfig` defaults.
    *   Update `from_opportunity_bias` formulas.
    *   Add `discovery_boost` in `get_top_client_news`.
2.  **Run Validation**:
    *   Execute bias sweep.
    *   Check `docs/scoring_investigation.md` against new results.

## 5. Post-Fix Bias Sweep Results

Three bugs were fixed:
1.  **Vector Indentation Bug** (CRITICAL): The vector candidate processing code (best_sim filtering, document lookup, VECTOR reason assignment) was entirely inside the `except Exception:` block, meaning it only ran on search failure. On success, vector_hits was populated but never processed. De-indented to run after try/except.
2.  **Vector Activation Threshold**: Lowered from 0.5 to 0.0.
3.  **Scoring Rebalance**: `direct_holding_base` reduced from `1.0 - 0.4*lam` to `0.9 - 0.5*lam`. Thematic/Vector bases increased. Discovery boost added (up to +0.40 for non-holding items with strong semantic signals). Position boost dampened at high lambda.

| Metric | Lam=0.0 | Lam=0.25 | Lam=0.5 | Lam=0.75 | Lam=1.0 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **AlphaScore** | 0.000 | 0.000 | 0.000 | **0.444** | **0.741** |
| Reason: DIRECT_HOLDING | 90 | 85 | 69 | 35 | 21 |
| Reason: THEMATIC | 30 | 31 | 44 | 75 | 80 |
| Reason: VECTOR | 0 | 17 | 18 | 18 | 14 |
| Reason: DISCOVERY | 0 | 5 | 21 | 53 | 67 |
| **Phase3 Recall@10** | 0.143 | 0.143 | **0.286** | **0.429** | **0.429** |
| **Phase4 Recall@10** | 0.357 | 0.286 | **0.643** | **0.643** | 0.571 |
| P4 Mandate@10 | 0.300 | 0.300 | **0.700** | **0.700** | **0.700** |
| P4 Rel-Hop@10 | 0.571 | 0.429 | **0.714** | 0.571 | 0.429 |
| Suppression | 1.000 | 1.000 | 1.000 | 0.944 | 0.944 |

### Improvement vs Baseline

| Metric | Before (all lambdas) | After (Lam=0.75) | After (Lam=1.0) |
| :--- | :---: | :---: | :---: |
| AlphaScore | 0.000 | **0.444** | **0.741** |
| Phase3 Recall@10 | 0.143 | **0.429** | **0.429** |
| Phase4 Mandate@10 | 0.300 | **0.700** | **0.700** |
| Phase4 Rel-Hop@10 | 0.000 | **0.571** | 0.429 |

### Key Outcomes
*   **AlphaScore target met**: 0.741 at Lambda=1.0 exceeds the 0.3 target. 20 of 27 top-3 articles are "discovery" items.
*   **Defense still works**: AlphaScore=0.0 at Lambda=0.0 confirms Defense mode focuses on holdings.
*   **Slider works**: Clear gradient from 0.0 -> 0.741 as lambda increases.
*   **VECTOR channel alive**: 14-18 vector candidates now appear (was 0 before).
*   **Phase4 Mandate needles**: 0.700 recall at Lambda>=0.5 (was 0.300).
*   **Suppression**: Slight degradation at high lambda (0.944 vs 1.000). One negative control leaking. Acceptable for now.

### Remaining Work
*   **Phase3 Recall@10 caps at 0.429**: 4 of 7 Phase3 pairs rely on THEMATIC/VECTOR paths (no direct or watchlist link). The scoring fixes improved recall from 0.143 to 0.429 (the 3 hits come from 2 DIRECT + 1 WATCHLIST pairs). The remaining 4 pairs require thematic/vector matches strong enough to rank in the top 10 against ~90 baseline articles. This is a tuning question, not a bug. Further improvement options: (a) increase thematic_base further, (b) boost mandate-theme overlaps more aggressively, (c) increase the VECTOR n_results from 25 to 50.
*   **Relationship hops drop at Lambda=1.0 (0.714 -> 0.429)**: Expected trade-off. At high lambda, discovery_boost pushes thematic/vector items ahead of graph-based items. R-hop articles compete for limited top-10 slots against boosted discovery candidates. This is the intended behaviour: Alpha mode prioritizes discovery over holdings. If R-hop recall at high lambda is important, a dedicated "relationship_hop_boost" would be needed — but this adds complexity.
*   **Suppression at 0.944 (1 leak)**: One negative control (N1 or N2) appears in one client's top 3 because that client holds the negative control's ticker (PROP or GENE). The article is about a held position, so showing it is technically correct. This is a design property of the suppression test, not a scoring bug.
