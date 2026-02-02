# Client Profile Enhancements for Dual‑Perspective Coverage

Author: Sales Trading SME (UK Cash Equities)  
Date: 2026‑02‑02

## Purpose
Capture both holdings/watchlist‑driven coverage and mandate‑driven opportunity coverage in a consistent client profile. The ultimate goal is to support a **Sliding Scale of Relevance** that tunes coverage from "Pure Defense" (Maintenance) to "Pure Alpha" (Opportunistic) based on the client's mandate.

---

## 1) Client Profile Completeness Score (CPCS)

To measure the system's ability to serve a client, we calculate a weighted completeness score (0.0 to 1.0). This guides Sales Traders to fill gaps.

**Formula**: `Score = Σ (Section_Weight × Section_Completeness)`

| Section | Weight | Impact on Matching | Completion Criteria |
| :--- | :--- | :--- | :--- |
| **Holdings Data** | **35%** | Critical for "Maintenance" coverage. | Has > 0 `HAS_POSITION` relationships or `WATCHLIST` items. |
| **Mandate Context** | **35%** | Critical for "Idea" generation & ranking. | Types: `mandate_type`, `benchmark`, `horizon` are set. |
| **Constraints** | **20%** | Critical for filtering (Anti-Pitch). | `esg_constrained` is explicit; if True, `EXCLUDES` > 0. |
| **Engagement** | **10%** | Context for delivery (Time/Channel). | `primary_contact` and `alert_frequency` defined. |

---

## 2) Make Better Use of What Is There (No Schema Change)

### A. Existing ClientProfile fields to activate (Phase 1)
- `mandate_type`: Proxy for **Opportunity Bias** (e.g., Pension = Maintenance, Hedge Fund = Alpha).
- `benchmark`: Use to identify benchmark‑linked relevance.
- `horizon`: Use to shape recency weighting (shorter horizon = higher recency weight).
- `turnover_rate`: Use to shape urgency (higher turnover = more time‑sensitive).
- `esg_constrained`: Use to filter news and drive exclusions.
- `impact_threshold` + `alert_frequency`: Use to tune prioritization and feed filtering.

### B. Existing relationships that are defined but not populated
- `EXCLUDES` (ClientProfile → Company/Sector): enables ESG/ethical/sector exclusions.
- `SUBSCRIBED_TO` (Client → Sector/Region/EventType): enables mandate topics and proactive coverage.
- `BENCHMARKED_TO` (ClientProfile → Index): already defined; should influence relevance scoring.

### Immediate (no schema change) actions
- Apply `mandate_type`, `benchmark`, `horizon`, and `turnover_rate` in `get_top_client_news` scoring.
- **Categorize Response**: Explicitly tag items as `MAINTENANCE` (Holdings/Watchlist) vs `IDEA` (Mandate/Subscription) in the output.
- Populate `EXCLUDES` and `SUBSCRIBED_TO` during client onboarding and profile updates.
- Surface these fields in the Client 360 header and show their effect on news relevance.

---

## 3) Extend Client Profile (Schema + API Extension)

### A. Mandate & "Sliding Scale" Structure
- `opportunity_bias`: Float (0.0–1.0) tuning the ratio of Holdings vs. Ideas.
  - `0.0` (Pure Defense): Only Holdings/Watchlist.
  - `1.0` (Pure Alpha): Heavy weight on themes/sectors.
- `investment_themes`: list of themes (e.g., AI, Clean Energy, Emerging Tech, Healthcare Innovation).
- `sector_focus`: `{ overweight[], underweight[], excluded[] }`.
- `geography_focus`: `{ home_bias, regions_allowed[], regions_excluded[] }`.

### B. Constraints & "Anti-Pitch"
- `esg_policy`: `NONE | EXCLUSION_ONLY | INTEGRATION | IMPACT | ENGAGEMENT`.
- `esg_exclusions`: categories (Coal, Tobacco, Weapons, Gambling).
- `liquidity_min_opportunistic`: Hard ADV/Cap filter for *new ideas* (ignored for existing holdings).
- `recent_exits`: List of recently sold assets (automatic "cool-off" exclusion).
- `max_position_size`, `single_stock_limit`.

### C. Trading preferences
- `trading_style`: `PATIENT | OPPORTUNISTIC | AGGRESSIVE`.
- `preferred_execution`: `ALGO | WORKED | BLOCK | RISK`.
- `typical_order_size`: `SMALL | MEDIUM | LARGE | BLOCK`.
- `time_zone`: coverage hours.

### D. Relationship context (coverage)
- `coverage_priority`: `TIER_1 | TIER_2 | TIER_3`.
- `primary_contact`, `last_meeting`, `meeting_frequency`.
- `communication_preference`, `notes`.

---

---

## Benefits
- Enables true dual‑perspective coverage:
   - **Maintenance (Defensive)**: "What did I miss on what I own?"
   - **Idea Generation (Opportunistic)**: "What fits my mandate that I don't own?"
- **Sliding Scale**: Adapt to client mode (Pension vs. Hedge Fund).
- **Smart Filtering**:
   - **Liquidity**: Don't pitch illiquid stocks to large funds.
   - **Anti-Pitch**: Don't pitch recently exited names.
- Improves relevance scoring beyond generic semantic matching.

---

## Next Steps
- **Phase 1**: Populate and surface existing fields; categorize output as Maintenance vs Idea.
- **Phase 2**: Extend schema (Opportunity Bias, Liquidity, Anti-Pitch); update scoring.

---

## Phase 1 Implementation Plan (Use What Exists)

### Step 1: Implement Profile Completeness Metric
**Goal**: Establish a baseline metric (0-1) to measure how well we can serve each client.
**Scope**: New logic in `ClientService`, exposed via MCP.
**Actions**:
- Implement `calculate_profile_completeness(client_graph_data) -> float`.
  - **Holdings (35%)**: 1.0 if `count(HAS_POSITION) + count(WATCHLIST) > 0`, else 0.
  - **Mandate (35%)**: 0.33 each for `mandate_type`, `benchmark`, `horizon`.
  - **Constraints (20%)**: 1.0 if `esg_constrained` is not null. (Bonus check: if true, `EXCLUDES` > 0).
  - **Engagement (10%)**: 1.0 if `primary_contact` and `alert_frequency` exist.
- Expose via MCP:
  - `get_client_profile_score(guid)`: Returns score breakdown.
  - Update `list_clients`: Sort/filter by `completeness_score`.
- **UI/Sales usage**: "Show me clients with Score < 0.5" (Blind spots).

**Test**: Unit tests for score calculation; verify MCP returns score.

---

### Step 2: Inventory Current Coverage Data
**Goal**: Use the new Scoring Metric to audit the book.
**Scope**: Run the metric across all clients.
**Actions**:
- Script/Tool to generate a `ProfileGapReport`.
- Identify "High Value, Low Score" clients (e.g., Big Holdco, no holdings loaded).
- Prioritize backfill based on the Score gaps.

**Test**: Gap report generated; low-score clients identified.

---

### Step 3: Populate Existing Fields in Onboarding/Updates
**Goal**: Ensure the existing fields are consistently set to improve the Score.
**Scope**: Use only existing schema and current MCP tools.
**Actions**:
- Update onboarding checklist to require values for:
   - `mandate_type` (Proxy for Opportunity Bias), `benchmark`, `horizon`, `turnover_rate`, `esg_constrained`.
- Add validation in onboarding workflows (UI/ops) to prevent empty values.
- Backfill critical clients using existing update mechanisms.

**Test**: Sample clients show full profile completeness.

---

### Step 4: Populate Existing Relationships
**Goal**: Use already-defined relationships.
**Scope**: No new relationship types.
**Actions**:
- Populate `EXCLUDES` (ClientProfile → Company/Sector) for ESG-constrained clients.
- Populate `SUBSCRIBED_TO` (Client → Sector/Region/EventType) for proactive coverage.
- Ensure `BENCHMARKED_TO` is set where a benchmark exists.

**Test**: Relationship coverage report; random spot checks in Neo4j.

---

### Step 5: Apply Existing Fields in Scoring & Response
**Goal**: Use what is already stored to improve ranking quality and output utility.
**Scope**: No new fields; only read existing ones.
**Actions**:
- Use `mandate_type`, `horizon`, and `turnover_rate` to adjust recency/urgency weights.
- Use `benchmark` to boost benchmark‑linked relevance.
- **Tag Output**: Add `category` field to `get_top_client_news` response:
  - If `HAS_POSITION` or `WATCHLIST`: `category="MAINTENANCE"`
  - Else: `category="IDEA"`
- Use `esg_constrained` plus `EXCLUDES` to filter coverage.

**Test**: Verify output includes category tags and reflects mandate bias.

---

### Step 6: Surface Existing Fields in Client 360
**Goal**: Make profile context visible to sales/trading.
**Scope**: Display only; no schema changes.
**Actions**:
- Display existing fields and relationships in Client 360 header/sidebar.
- Show **Completeness Score** visual (e.g., progress bar) to prompt updates.
- Show why a story was selected (benchmark, subscription, mandate, horizon).
- highlight `MAINTENANCE` vs `IDEA` distinction in the feed.

**Test**: UI shows all current fields and relationships for target clients.

---

### Step 7: Validate with E2E Scenarios (Sales Trader Review)
**Goal**: Confirm improved coverage outcomes match trader intuition.
**Scope**: Use existing tools and data.
**Actions**:
- Create test clients: one "Defensive Pension" and one "Alpha Hedge Fund".
- Ingest stories: some specific to holdings, some thematic ideas.
- Verify Pension gets mostly Maintenance updates.
- Verify Hedge Fund gets mixed Maintenance/Ideas based on mandate.
- Verify exclusions work.

**Test**: E2E checklist passes; trader sign-off on relevance.

---

### Success Criteria
- [ ] Profile Completeness Score implemented and visible via MCP.
- [ ] Existing profile fields are consistently populated for priority clients.
- [ ] `EXCLUDES`, `SUBSCRIBED_TO`, and `BENCHMARKED_TO` are populated where applicable.
- [ ] `get_top_client_news` output distinguishes **Maintenance** vs **Idea**.
- [ ] Ranking reflects mandate (proxy for bias), horizon, turnover, and benchmark.
- [ ] Client 360 displays profile context and story reasons.

---

## Review Notes (Functional Gaps + Simplifications)

### Functional Gaps (Sales/Trading)
- **Idea vs Maintenance**: Critical distinction for workflow (IM vs Call).
- **Anti-Pitch**: Need `RECENTLY_EXITED` to avoid awkward pitches.
- **Liquidity Filters**: Essential to avoid irrelevant alpha ideas.
- Coverage timing preferences (market hours, regional focus, liquidity windows).
- Trading constraints (shorting allowed, ADV limits, vol tolerance).

### Technical Risks / Simplifications
- Enforce enums for `mandate_type`, `horizon`, and `turnover_rate` to avoid free‑form drift.
- Separate candidate selection vs ranking to keep `get_top_client_news` explainable.
- Use a centralized weight config to tune without code changes.
- Ensure deterministic mappings for benchmarks, sectors, and event types.

