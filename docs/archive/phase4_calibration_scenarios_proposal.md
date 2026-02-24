# Proposal: Phase 4 Calibration Scenarios for the Simulator

Date: 2026-02-21

## Summary
Phase 3 proves the new ranking pipeline works in a clean, controlled setting, but Phase 4 tuning needs a repeatable way to validate:
- client-specific relevance (the right client sees the right story),
- relationship traversal/influence logic under realistic competition,
- and a measurable response curve as $\lambda$ moves from holdings-heavy to thematic-heavy.

This proposal upgrades the simulator by adding Phase 4 calibration scenarios that explicitly target different client mandates and encode the expected client(s) in the synthetic story metadata.

The key deliverable is a deterministic, small "needle set" that can be injected into a large noisy background corpus and then scored by the avatar harness.

## Why Phase 4 Needs New Scenarios
The current generator does create diverse stories, but for tuning we need:
1) mandate-targeted non-holding candidates for multiple client archetypes (not just a single Phase3 B needle),
2) explicit, machine-checkable expectations about which client(s) should rank the story,
3) negative controls (stories that should NOT rank for certain clients),
4) enough repeated, comparable cases to diagnose "flat across lambdas" failure modes.

## Design Constraints
- Keep the simulation workflow the same: background corpus generation, then injection of calibration stories.
- Titles must be deterministic and unique for matching in the avatar harness.
- Each calibration story must embed:
  - `validation_metadata.scenario` (prefix `Phase4`),
  - `validation_metadata.base_ticker` (canonical ticker used for matching/debug),
  - `validation_metadata.expected_relevant_clients` (stable client GUID list).
- Calibration stories must be recent (within the query window used by the MCP tools).
- The stories must remain "LLM-safe": prompts must explicitly constrain tickers/companies to those in the provided universe.

## Current Client Set (Stable GUIDs)
From `simulation/generate_synthetic_clients.py` the stable clients are:
- 550e8400-e29b-41d4-a716-446655440001  Quantum Momentum Partners (themes: ai, semiconductor)
- 550e8400-e29b-41d4-a716-446655440002  Nebula Retirement Fund (themes: commodities, rates)
- 550e8400-e29b-41d4-a716-446655440003  DiamondHands420 (themes: blockchain, ev_battery)
- 550e8400-e29b-41d4-a716-446655440004  Green Horizon Capital (themes: esg, energy_transition)
- 550e8400-e29b-41d4-a716-446655440005  Sunrise Long Opportunities (themes: cloud, consumer)
- 550e8400-e29b-41d4-a716-446655440006  Ironclad Short Strategies (themes: credit, geopolitical)

Note: `simulation/generate_synthetic_stories.py` currently only includes 3 clients in `CLIENT_PORTFOLIOS`. Phase 4 calibration work should align story generation metadata to include all six clients, or otherwise explicitly define expected client sets for calibration scenarios.

## Proposed Phase 4 Calibration Scenario Set
Each scenario is intended to be generated exactly once per run (like Phase 3), with deterministic titles:
- Title format: `[Phase4 <ScenarioId> <ShortName>] <BASE_TICKER> - <Key Theme>`

### Group A: Mandate-targeted non-holding needles (primary $\lambda$ curve drivers)
These are designed to outrank holding-driven items only as $\lambda$ increases (or at least meaningfully improve rank).

1) Phase4 M1 AI Compute Supply Chain (Quantum Momentum Partners)
- Expected clients: [0001]
- Base ticker: choose a universe ticker with AI/semiconductor adjacency that is NOT necessarily a holding (or use a watchlist name if we want partial overlap).
- Prompt intent: non-holding thematic catalyst (data-center GPU demand, foundry constraint, packaging bottleneck).
- Validation goal: rank improves as $\lambda$ rises; proves mandate embedding + vector/thematic retrieval is actually contributing.

2) Phase4 M2 Rates Shock / Inflation Print (Nebula Retirement Fund)
- Expected clients: [0002]
- Base ticker: a rates/commodities-sensitive ticker from factor exposures.
- Prompt intent: macro release that should matter more to rates/commodities mandate than to tech momentum clients.
- Validation goal: client-specific (0002) rank strong; non-0002 clients should not consistently surface it.

3) Phase4 M3 Crypto Protocol Exploit / Regulatory Headline (DiamondHands420)
- Expected clients: [0003]
- Base ticker: blockchain-related universe ticker.
- Prompt intent: high-signal catalyst with retail sentiment flavor.
- Validation goal: high for retail thematic; provides a non-holding competitor to holdings-driven items for other clients.

4) Phase4 M4 Energy Transition Policy Catalyst (Green Horizon Capital)
- Expected clients: [0004]
- Base ticker: ECO/STR or a related transition ticker (can be holding or non-holding depending on what we want to test).
- Prompt intent: subsidy/policy/regulatory change that should rank highly for ESG mandate.
- Validation goal: tests restriction-aware relevance (if restrictions are active in scoring/filtering) and thematic retrieval.

5) Phase4 M5 Cloud Pricing / SaaS Demand Shift (Sunrise Long Opportunities)
- Expected clients: [0005]
- Base ticker: GTX/SHOPM (or a non-holding cloud/consumer ticker).
- Prompt intent: mandate-aligned story that should gain weight at higher $\lambda$.

6) Phase4 M6 Credit Downgrade / Geopolitical Shock (Ironclad Short Strategies)
- Expected clients: [0006]
- Base ticker: a credit/geopolitical sensitive ticker (or a portfolio short name if we want to test short-side semantics).
- Prompt intent: downside catalyst suited to a short-bias mandate.

### Group B: Relationship-hop calibration (graph traversal / influence boost)
These are designed to validate relationship traversal works on a client-specific basis under competition.

7) Phase4 R1 Supplier-to-Holding Impact (1 hop)
- Expected clients: choose exactly one client whose holding is the downstream impacted ticker.
- Structure: headline focuses on supplier; body explicitly explains downstream impact to the holding.
- Validation goal: if relationship edges/path counting are broken, this story drops out for the intended client.

8) Phase4 R2 Competitor-to-Holding Opportunity (2 hops)
- Expected clients: choose a client holding the beneficiary ticker.
- Structure: competitor failure/recall; beneficiary is mentioned as opportunity.
- Validation goal: tests 2-hop traversal + scoring boost.

9) Phase4 R3 Multi-ticker systemic shock (influence boost)
- Expected clients: a client holding 2-3 affected tickers (or multiple clients if intentionally shared).
- Structure: story explicitly mentions all impacted tickers.
- Validation goal: influence/path boost should make this outrank single-name items, especially at low/mid $\lambda$.

### Group C: Negative controls (suppression tests)
These are designed to ensure the algorithm does NOT over-trigger.

10) Phase4 N1 Generic Sector Chatter (noise)
- Expected clients: []
- Validation goal: should not land in Top 3 for any client.

11) Phase4 N2 Wrong-theme strong headline (false positive guard)
- Expected clients: pick a client where the content is intentionally off-mandate and off-holdings.
- Validation goal: avoids systematic false positives in thematic matching.

## How These Scenarios Enable Verification

### Client-specific ranking
Each Phase4 calibration story encodes `expected_relevant_clients`. The harness checks that for each (case, client) pair:
- the intended story is present in Top K (Recall@K), and
- the rank trends in the expected direction across $\lambda$.

### Relationship traversal
Relationship-hop scenarios are structured so that:
- the client only becomes a candidate via graph traversal (supplier/competitor links),
- not via direct holdings overlap.

If traversal/influence is broken, the story will not appear (or will rank far lower) for the intended client.

### Bias response and crossover
Mandate-targeted needles provide comparable non-holding candidates across multiple client archetypes.
With a large background corpus (e.g., 500 docs), the ranking function is forced to choose.

If results are flat across $\lambda$, we can isolate whether the problem is:
- candidate generation (vector/thematic candidates not entering),
- scoring weights not applied,
- or calibration cases not strong enough.

## Proposed Simulator UX / Injection Workflow
- Add a generation mode flag similar to Phase 3:
  - `./simulation/run_simulation.sh --phase4 --regenerate`
  - Semantics: generate exactly one story per Phase4 calibration scenario and ingest them.
- Keep weights for Phase4 scenarios low (or zero) in the general random pool to avoid "accidental" re-generation; prefer explicit `--phase4` selection.

Suggested workflow for Phase 4 tuning:
1) `./simulation/run_simulation.sh --count 500 --regenerate`
2) `./simulation/run_simulation.sh --phase4 --regenerate` (inject the calibration set)
3) `uv run python simulation/validate_avatar_feeds.py --bias-sweep --lambdas 0,0.25,0.5,0.75,1`

## Avatar Simulation Fit
The avatar simulation is the measurement harness:
- Phase 3: prove algorithm correctness on a small controlled set.
- Phase 4: regression harness + tuning dashboard against a large noisy corpus.

Proposed enhancement (optional but recommended):
- Extend `validate_avatar_feeds.py` to load both `Phase3*` and `Phase4*` cases, and report:
  - Recall@3 (or @5) per scenario group,
  - rank deltas vs $\lambda$ for mandate needles.

## Acceptance Criteria
- A Phase4 run produces exactly one JSON per Phase4 scenario in `simulation/test_output/` with correct validation metadata.
- After injecting Phase4 into a 500 background corpus:
  - For each scenario, the intended client(s) have Recall@3 >= target (e.g., 0.8+ per group) while non-intended clients do not systematically recall it.
  - Mandate needles show a measurable rank improvement as $\lambda$ increases (directional, not necessarily monotonic every time).
  - Relationship-hop cases appear for intended clients even when the holding ticker is not the headline subject.

## Risks / Open Questions
- Universe coverage: we need tickers that cleanly map to each mandate theme; may require picking specific known tickers in the universe.
- Current story generator metadata only knows 3 client portfolios; proposal assumes we align it to 6 stable clients.
- If the vector/thematic candidate path depends on embeddings being present, Phase4 tuning must ensure client embeddings and doc theme tags are populated.

## Next Steps (Requires Approval)
1) Decide the exact Phase4 scenario list (minimum viable set: 6 mandate needles + 3 relationship cases + 1 noise control).
2) Update simulator generator to support `--phase4` and deterministic titles.
3) Align client portfolio/watchlist metadata in `generate_synthetic_stories.py` with the full stable client set.
4) Extend avatar validation to score Phase4 cases (or add a new validation script focused on Phase4).