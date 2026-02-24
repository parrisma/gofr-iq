# Implementation Plan: Phase 4 Calibration Scenarios (Simulator)

Date: 2026-02-21

This plan implements the approved proposal in docs/phase4_calibration_scenarios_proposal.md.

## Scope
Add a deterministic Phase 4 calibration scenario set that:
- targets multiple stable client mandates,
- encodes expected clients in validation metadata,
- and is measurable via the avatar validation harness.

## Step-by-step

1) Align simulation metadata with the stable client set
- Update simulation/generate_synthetic_stories.py
  - Expand CLIENT_PORTFOLIOS to include all stable clients (GUIDs 0001..0006) with holdings matching simulation/generate_synthetic_clients.py.
  - Expand CLIENT_WATCHLISTS to be keyed by those GUIDs (not "client-hedge-fund" style strings).
- Exit criteria: generator can compute expected_clients across all six clients.

2) Add Phase4 calibration scenarios
- Update simulation/generate_synthetic_stories.py
  - Add Phase4 scenarios to SCENARIOS (but do not rely on weights for selection).
  - Add deterministic generation selection list (like Phase3): scenarios whose name starts with "Phase4".
  - Ensure titles are deterministic and unique per scenario.
  - Ensure validation metadata contains:
    - scenario (Phase4 prefix)
    - base_ticker
    - expected_relevant_clients
- Exit criteria: `--phase4` generates exactly one JSON per Phase4 scenario.

3) Add runner flag and wiring
- Update simulation/run_simulation.py
  - Add `--phase4` flag.
  - When set, override effective_count to the number of Phase4 scenarios.
  - Ensure generation stage uses scenarios_override for Phase4.
  - Ensure ingestion stage filters scenario_prefix="Phase4" when running `--phase4`.
- Update simulation/run_simulation.sh
  - No changes expected; it forwards args.
- Exit criteria: `./simulation/run_simulation.sh --phase4 --regenerate` generates + ingests Phase4 cases and passes gates.

4) Extend avatar harness to evaluate Phase4 cases
- Update simulation/validate_avatar_feeds.py
  - Load both Phase3 and Phase4 cases from simulation/test_output.
  - Keep Phase3 behavior the same (Phase3 D excluded).
  - Define which Phase4 negative controls should be excluded from Recall@3 (e.g., Phase4 N1 noise).
  - Report metrics per group:
    - Phase3 Recall@3
    - Phase4 Recall@3 (mandate needles)
    - Phase4 Recall@3 (relationship cases)
    - Optional: negative control suppression rate
- Exit criteria: `--bias-sweep` prints Phase4 metrics without breaking existing Phase3 output.

5) Validation runs
- Smoke:
  - `./simulation/run_simulation.sh --count 50 --regenerate`
  - `./simulation/run_simulation.sh --phase4 --regenerate`
  - `uv run python simulation/validate_avatar_feeds.py --bias-sweep --lambdas 0,0.25,0.5,0.75,1`
- Full test suite:
  - `./scripts/run_tests.sh`

## Non-goals
- Do not change core scoring logic in this milestone.
- Do not introduce new services or async rewrites.

## Risks / Mitigations
- If Phase4 cases don’t surface at any lambda:
  - Diagnose candidate generation (vector path, theme tagging, mandate embeddings) before tweaking weights.
- If Phase4 cases surface for the wrong clients:
  - Tighten tickers/theme specificity in prompts and/or adjust expected_relevant_clients to match the simulation holdings/watchlists.
