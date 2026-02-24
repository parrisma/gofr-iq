# Phase 3 Scenario Redesign Proposal

## Problem

Phase 3 scenarios define `expected_relevant_clients` that have no viable
scoring path to the generated articles. The bias sweep correctly scores
AlphaScore = 0.741 overall, but Phase 3 recall is capped because the
expectations are physically unreachable given the current client profiles,
graph topology, and scoring weights.

This is a test-design bug, not a scoring bug.

## Root Cause Analysis

Each Phase 3 scenario was authored with comments claiming that "lateral
graph hops" (COMPETES_WITH, PARTNER_OF) would route articles to the
expected clients. In practice:

1. Lateral hop base scores (competitor_base = 0.4 + 0.3*lambda) are
   structurally lower than direct-holding scores on competing articles,
   so they rarely survive the top-K ranking.
2. Even when lateral candidates enter the pool, they lack the
   position_weight_boost that direct holdings receive, and they have no
   thematic or vector reinforcement for the expected clients.
3. The expected clients often have ZERO theme overlap with the article,
   so neither the THEMATIC nor VECTOR channels fire.

The result: the scenario expects a client to find an article, but no
scoring channel produces a signal strong enough to surface it.

## Per-Scenario Diagnosis

### Phase3 A -- Defense Tail Holding Failure (NXS)

**Expected clients:** 440001, 440005

| Client | Route | Viable? |
|--------|-------|---------|
| 440001 (Quantum Momentum) | Holds NXS (0.5%), DIRECT_HOLDING channel | Yes |
| 440005 (Sunrise Long) | Holdings: QNTM, SHOPM, GTX. Themes: cloud, consumer | No |

440005's intended route: NXS -> COMPETES_WITH -> GTX (both Technology) ->
440005 holds GTX. But the COMPETITOR base at any lambda is weaker than
direct-holding scores on other articles competing for 440005's feed. And
440005's mandate themes (cloud, consumer) have no overlap with an NXS
cybersecurity/operational-failure article, so THEMATIC and VECTOR channels
do not reinforce the lateral signal.

**Verdict:** 440005 is unreachable.

### Phase3 B -- Offense Thematic M&A (LUXE)

**Expected clients:** 440003, 440002, 440004, 440005

| Client | Route | Viable? |
|--------|-------|---------|
| 440003 (DiamondHands420) | LUXE on watchlist, WATCHLIST channel | Yes |
| 440002 (Nebula Retirement) | Holds SHOPM; LUXE COMPETES_WITH SHOPM (both Consumer Cyclical). Themes: commodities, rates | No |
| 440004 (Green Horizon) | Holds SHOPM; same COMPETES_WITH route. Themes: esg, energy_transition | No |
| 440005 (Sunrise Long) | Holds SHOPM; same COMPETES_WITH route. Themes: cloud, consumer | Marginal |

For 440002 and 440004 the only path is LUXE -> COMPETES_WITH -> SHOPM.
This produces a COMPETITOR score of at best 0.70 (lambda=1.0). But the
article has no thematic or vector overlap with "commodities/rates" or
"esg/energy_transition", so there is no reinforcement and the lateral
candidate is outranked.

440005 has a marginal path because "consumer" theme could match the
article's Consumer Cyclical sector classification, but the ingested
article's actual themes are "m_and_a" and "consumer" -- so if the
THEMATIC channel picks up "consumer" it may work, but only at high
lambda. This is fragile.

**Verdict:** 440002 and 440004 are unreachable. 440005 is marginal.

### Phase3 C -- Systemic Multi-Holding Shock (QNTM/BANKO/VIT)

**Expected clients:** 440001

| Client | Route | Viable? |
|--------|-------|---------|
| 440001 (Quantum Momentum) | Holds all three tickers | Yes |

**Verdict:** Correct as designed. No changes needed.

### Phase3 D -- Noise Generic Sector Chatter

**Expected clients:** [] (empty -- noise suppression control)

**Verdict:** Correct as designed. No changes needed.

## Fix Options

### Option A: Shrink expected_relevant_clients (honest expectations)

Remove clients that have no credible scoring path. This acknowledges
that the scoring engine is working correctly and aligns test expectations
with reality.

Changes:

| Scenario | Current | Proposed |
|----------|---------|----------|
| Phase3 A | [440001, 440005] | [440001] |
| Phase3 B | [440003, 440002, 440004, 440005] | [440003] |
| Phase3 C | [440001] | [440001] (unchanged) |
| Phase3 D | [] | [] (unchanged) |

**Upside:** Immediately correct. Phase 3 recall rises from ~0.33 to
~1.0. No scoring or ingestion changes needed.

**Downside:** Reduces Phase 3 test surface from 7 client-article pairs
to 3. Does not exercise lateral or thematic discovery at all.

### Option B: Enrich client profiles to create credible routing paths

Add mandate themes or watchlist entries to the expected clients so that
at least one non-lateral channel (THEMATIC, VECTOR, or WATCHLIST) can
fire. This creates real test coverage for multi-channel scoring.

Proposed profile changes:

**Phase3 A (NXS -- operational failure / cybersecurity):**

- Add "cybersecurity" to 440005's mandate_themes (cloud, consumer, cybersecurity).
  Rationale: A cloud-infrastructure fund plausibly monitors cyber risk.
  This gives 440005 a THEMATIC route to NXS articles tagged "cybersecurity".

**Phase3 B (LUXE -- competitor M&A / consumer luxury):**

- Add "consumer" to 440002's mandate_themes (commodities, rates, consumer).
  Rationale: A diversified pension fund holding SHOPM (consumer bellwether)
  plausibly tracks consumer trends. This matches the article's "consumer" theme.
- Add "LUXE" to 440005's watchlist (currently: VIT, ECO; proposed: VIT, ECO, LUXE).
  Rationale: A long-bias consumer-theme fund watching luxury M&A is natural.
  This gives 440005 a WATCHLIST path.
- Drop 440004 from expected_relevant_clients. Green Horizon's ESG/energy
  mandate has no plausible connection to luxury M&A. Forcing it would
  require unnatural profile distortion.

Resulting expected_relevant_clients:

| Scenario | Current | Proposed |
|----------|---------|----------|
| Phase3 A | [440001, 440005] | [440001, 440005] (unchanged, but now routable) |
| Phase3 B | [440003, 440002, 440004, 440005] | [440003, 440002, 440005] |
| Phase3 C | [440001] | [440001] (unchanged) |
| Phase3 D | [] | [] (unchanged) |

**Upside:** Maintains broader test surface (6 client-article pairs).
Exercises THEMATIC and WATCHLIST channels in addition to direct holdings.
Profile changes are minimal and narratively believable.

**Downside:** Modifies client profiles, which may affect Phase 4
scenario outcomes (must re-validate). Requires regenerating client
data and re-running the full pipeline.

### Option C: Hybrid (recommended)

Apply Option B's profile enrichments where they are narratively credible,
and apply Option A's pruning for the remaining unreachable pairs. This
maximizes test coverage without distorting client profiles.

Concrete changes:

1. **generate_synthetic_clients.py**
   - 440005 (Sunrise Long): add "cybersecurity" to mandate_themes.
     New: ["cloud", "consumer", "cybersecurity"]
   - 440002 (Nebula Retirement): add "consumer" to mandate_themes.
     New: ["commodities", "rates", "consumer"]
   - 440005 (Sunrise Long): add "LUXE" to watchlist.
     New: ["VIT", "ECO", "LUXE"]

2. **generate_synthetic_stories.py**
   - Phase3 A: keep expected_relevant_clients = [440001, 440005]
   - Phase3 B: change to [440003, 440002, 440005] (drop 440004)
   - Phase3 C: no change
   - Phase3 D: no change

3. **Re-validation**
   - Regenerate clients, regenerate Phase 3 + Phase 4 stories, re-ingest.
   - Run full bias sweep to confirm Phase 3 recall improves and Phase 4
     metrics do not regress.
   - Verify Phase 4 expected_relevant_clients are still correct after
     the profile changes.

## Impact Assessment

| Metric | Before | After (projected) |
|--------|--------|--------------------|
| Phase 3 client-article pairs | 7 | 6 |
| Phase 3 reachable pairs | 3 | 6 |
| Phase 3 un-reachable pairs | 4 | 0 |
| Scoring channels exercised | DIRECT_HOLDING, WATCHLIST | DIRECT_HOLDING, WATCHLIST, THEMATIC |
| Client profiles modified | 0 | 2 (440002, 440005) |
| Phase 4 re-validation | N/A | Required |

## Risks

1. Adding "cybersecurity" to 440005 could make Phase 4 cyber-themed
   articles unexpectedly appear in 440005's feed. Mitigation: audit Phase 4
   scenario expected lists after the change.

2. Adding "consumer" to 440002 broadens the pension fund's thematic
   surface. This is realistic (SHOPM is a consumer holding) but may
   introduce marginal recall changes in Phase 4. Mitigation: same
   audit.

3. Adding LUXE to 440005's watchlist creates a WATCHLIST route for any
   LUXE article, not just Phase 3 B. Mitigation: acceptable -- the fund
   already tracks consumer themes and LUXE is Consumer Cyclical.

## Recommendation

Implement Option C (hybrid). The two profile enrichments are small,
narratively justified, and resolve 3 of the 4 unreachable pairs. The
fourth unreachable pair (440004 / Phase3 B) is dropped because no
credible routing path exists without distorting the ESG fund's mandate.
