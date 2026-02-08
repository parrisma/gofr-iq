# Avatar Feed Gap Plan

**The trader's question every morning:** "What do I need to know about my clients'
books RIGHT NOW, and what new ideas can I bring them?"

That is the entire product. Every test below exists to prove gofr-iq answers that
question correctly, completely, and fast.

## Where We Are

The two-channel avatar feed (MAINTENANCE + OPPORTUNITY) works end to end. A basic
deterministic golden set (5 docs, 4 clients) passes. But the evidence is shallow:

- **Opportunity channel is the differentiator but the weakest link.** It depends on
  LLM-extracted mandate themes matching document themes. The current synthetic clients
  all have generic "global macro" mandates, so opportunities either match everything
  or nothing -- you cannot tell if the matching logic actually works.
- **No ranking proof.** We check items appear but never prove the MOST important item
  floats to position 1. A trader who sees noise at the top stops trusting the feed.
- **No false-positive proof.** We check expected hits but never assert expected misses.
  One irrelevant story in a client feed destroys credibility faster than a missing one.
- **Report says PASS/FAIL but not WHY.** A trader needs to explain in five seconds why
  they are calling. The test should prove the system gives them that sentence.

---

## Force-Ranked Priorities

### P1: Make Opportunity Actually Work (highest impact)

The opportunity channel is what separates gofr-iq from a dumb ticker alert. Right now
it cannot be tested because every client has the same mandate themes.

**What to do (one change set, three files):**

1. Give each synthetic client distinct, realistic mandate_themes on the MockClient
   object in `simulation/generate_synthetic_clients.py`:
   - Quantum Momentum: ai, semiconductor (fast-moving tech desk)
   - Green Horizon: clean_energy, esg, energy_transition (ESG mandate)
   - Ironclad Short: credit, geopolitical (macro downside)
   - Nebula Retirement: commodities, rates (conservative macro)
2. Align test doc themes in `simulation/test_data/avatar_test_set.json` so each doc
   has a clear expected owner in OPPORTUNITY (not just MAINTENANCE):
   - Green Energy Bill (clean_energy) -> Green Horizon OPPORTUNITY
   - AI Breakthrough (ai, semiconductor) -> Quantum OPPORTUNITY
   - Gene Trial Fail (biotech) -> nobody (control doc)
3. Persist mandate_themes directly to the Neo4j ClientProfile node at creation time
   in `simulation/load_simulation_data.py`, bypassing the LLM enrichment path for
   test clients so the result is fully deterministic.

**Test assertion:** For each golden doc, assert it appears in the expected client's
OPPORTUNITY channel and does NOT appear in any other client's OPPORTUNITY channel.

**Evidence this produces:** Proof that the system can match a new idea to the right
desk based on what they care about -- not just what they own.

### P2: Prove Ranking Quality (second highest impact)

A feed that shows noise at the top is worse than no feed. The trader calls on the
top item. It must be the right one.

**What to do:**

1. Add a ranking assertion to validate_test_set.py: for each client, the combined
   feed's top item must be the highest-impact doc that affects their holdings or
   matches their mandate.
2. Add a weight-sensitivity check: a story affecting a 20% position must rank above
   the same-impact story affecting a 5% position for the same client.

**Test assertion:** Top-1 item per client matches the expected highest-priority doc.
Top-3 items contain at least one PLATINUM/GOLD event relevant to the client.

**Evidence:** Proof the trader would call about the right thing first.

### P3: Prove No False Positives (trust)

One wrong story and the trader stops reading. This is the trust test.

**What to do:**

1. Define expected misses in the golden set expectations:
   - Gene Trial (affects GENE) must NOT appear for any client (nobody holds GENE).
   - BankOne Earnings (score 25) must NOT appear for Quantum (threshold 40).
2. Add explicit "must NOT appear" assertions in validate_test_set.py for each
   expected miss.
3. Add a group access check: every item in a feed must belong to a group the token
   permits. Zero cross-group leakage.

**Test assertion:** Named docs do not appear. No item has a group_guid outside the
token's permitted set. Precision proxy >= 1.0 for golden set.

**Evidence:** Proof the system never shows irrelevant or unauthorized news.

### P4: Prove the "Why" Works (trader call script)

The trader needs one sentence: "Calling because X affects your Y position" or
"New opportunity in Z which fits your mandate." The feed's reason field must
deliver this.

**What to do:**

1. Assert reason field contains the matched ticker for MAINTENANCE items
   (eg "TRUCK" in reason when doc affects TRUCK holding).
2. Assert reason field contains the matched theme for OPPORTUNITY items
   (eg "clean_energy" in reason).
3. Add a one-line per-client "call script" to the report: top item title + reason.
   This is what a stakeholder reads to judge the product.

**Test assertion:** Every feed item has a non-empty reason containing either a
position ticker or a mandate theme as appropriate.

**Evidence:** Proof the trader can explain the call in five seconds.

### P5: Infrastructure Guardrails (foundation)

These do not generate trader-visible value directly but prevent silent corruption.

**What to do:**

1. **Clean state gate:** Before deterministic injection, assert the graph has the
   expected number of clients and zero test documents. Fail fast if dirty.
2. **Theme vocabulary gate:** Every document theme and client mandate_theme must be
   in the controlled vocabulary (VALID_THEMES). Zero out-of-vocab tags.
3. **Empty feed guard:** --require-nonempty is default for the golden set run.
4. **Idempotent injection:** inject_test_data.py uses MERGE so repeated runs cannot
   create duplicates.

**Test assertion:** Pre-flight checks pass before any data is injected. Post-flight
checks confirm schema completeness (impact_score, impact_tier, themes, created_at
present on every doc node).

---

## Execution Plan

Each step is small. Tests pass before and after.

| Step | Files Changed | What It Proves |
|------|--------------|----------------|
| 1 | generate_synthetic_clients.py | Clients have distinct mandate_themes |
| 2 | load_simulation_data.py | Themes persist to Neo4j without LLM |
| 3 | avatar_test_set.json | Docs align to client themes |
| 4 | validate_test_set.py | OPPORTUNITY assertions pass (P1) |
| 5 | validate_test_set.py | Ranking assertions pass (P2) |
| 6 | validate_test_set.py | False-positive assertions pass (P3) |
| 7 | validate_test_set.py | Reason field assertions pass (P4) |
| 8 | run_avatar_simulation.sh | Pre-flight and vocab gates pass (P5) |

Run after each step: `./simulation/run_avatar_simulation.sh --test-set`

---

## KPI Summary (per client, every run)

| KPI | Target | What It Means |
|-----|--------|---------------|
| Coverage | 100% golden set | Every expected doc appears |
| Precision | 100% golden set | No unexpected docs appear |
| Top-1 correct | yes/no | Most important story is #1 |
| Reason valid | 100% | Every item has a usable call reason |
| Empty feeds | 0 | No client left without intelligence |
| Vocab violations | 0 | No rogue themes |
| Group leakage | 0 | No cross-client data |

---

## Implementation Checklist

Precondition: existing golden set tests pass before starting.
Run `./simulation/run_avatar_simulation.sh --test-set` to confirm baseline.

### Step 1 -- Add mandate_themes to MockClient (P1)

Files: `simulation/universe/types.py`, `simulation/generate_synthetic_clients.py`

- [ ] 1.1 Add `mandate_themes: list[str]` field to `MockClient` dataclass in types.py
      (default empty list, no existing code breaks).
- [ ] 1.2 Set distinct mandate_themes on each client in generate_synthetic_clients.py:
      - Quantum Momentum: ["ai", "semiconductor"]
      - Green Horizon: ["clean_energy", "esg", "energy_transition"]
      - Ironclad Short: ["credit", "geopolitical"]
      - Nebula Retirement: ["commodities", "rates"]
      - DiamondHands420: ["blockchain", "ev_battery"]
      - Sunrise Long: ["cloud", "consumer"]
- [ ] 1.3 Verify mandate_text for each client is coherent with its mandate_themes
      (update text if it contradicts the themes).
- [ ] 1.4 Run existing golden set -- confirm no regressions.

### Step 2 -- Persist mandate_themes to Neo4j (P1)

Files: `simulation/load_simulation_data.py`

- [ ] 2.1 In the client creation path, read mandate_themes from MockClient.
- [ ] 2.2 After create_client MCP call succeeds, write mandate_themes directly to
      the ClientProfile node via Cypher MERGE (same pattern as inject_test_data.py).
- [ ] 2.3 Skip LLM mandate enrichment when mandate_themes is already present
      (check: if client has explicit themes, do not call extract_themes_from_mandate).
- [ ] 2.4 Run probe_graph.py for each client, confirm mandate_themes property is set.
- [ ] 2.5 Run existing golden set -- confirm no regressions.

### Step 3 -- Align test doc themes to client themes (P1)

Files: `simulation/test_data/avatar_test_set.json`

- [ ] 3.1 Review each doc's simulated_impact.themes against the new client themes.
- [ ] 3.2 Add or adjust themes so at least one doc per client has an OPPORTUNITY match:
      - doc-test-02 (Green Energy Bill): themes include "clean_energy" -> Green Horizon
      - doc-test-03 (NXS AI Breakthrough): themes include "ai", "semiconductor" -> Quantum
      - Consider adding 1-2 docs for underserved clients (Ironclad, Nebula) if needed.
- [ ] 3.3 Confirm no doc matches ALL clients (that would prove nothing).
- [ ] 3.4 Write down the expected test matrix in a comment block at the top of the JSON.
- [ ] 3.5 Run golden set -- MAINTENANCE tests still pass.

### Step 4 -- Add OPPORTUNITY assertions to validator (P1)

Files: `simulation/scripts/validate_test_set.py`

- [ ] 4.1 Add test cases that assert specific docs appear in specific client
      OPPORTUNITY channels (eg Green Energy Bill in Green Horizon OPPORTUNITY).
- [ ] 4.2 Add negative assertions: doc must NOT appear in OPPORTUNITY for clients
      whose mandate_themes do not match (eg Green Energy Bill NOT in Quantum OPP).
- [ ] 4.3 Run golden set -- new OPPORTUNITY tests pass or fail revealing real gaps.
- [ ] 4.4 If tests fail, diagnose: is it a theme mismatch, a missing AFFECTS edge,
      or a scoring/filter issue? Fix the root cause, not the test.
- [ ] 4.5 All tests green. Commit with message "P1: opportunity channel deterministic".

### Step 5 -- Add ranking assertions (P2)

Files: `simulation/scripts/validate_test_set.py`

- [ ] 5.1 Define expected top-1 doc per client based on impact_score and position weight:
      - Quantum: doc-test-03 (NXS, score 95, PLATINUM) -- highest impact on watchlist
      - Nebula: doc-test-02 (ECO, score 85, GOLD) or doc-test-01 (TRUCK, score 60)
      - Green Horizon: doc-test-02 (ECO, score 85, holds ECO)
      - Ironclad: doc-test-01 (TRUCK, score 60, shorts TRUCK)
- [ ] 5.2 Add assertion: combined[0].document_guid == expected top-1 for each client.
- [ ] 5.3 Add assertion: at least one PLATINUM or GOLD item in top 3.
- [ ] 5.4 If a weight-sensitivity doc pair exists (same impact, different weights),
      assert heavier position ranks higher. If no pair exists, add one to test data.
- [ ] 5.5 Run golden set -- ranking tests pass.
- [ ] 5.6 Commit with message "P2: ranking quality proven".

### Step 6 -- Add false-positive assertions (P3)

Files: `simulation/scripts/validate_test_set.py`

- [ ] 6.1 Add "must NOT appear" list per client:
      - All clients: doc-test-04 (Gene Trial, GENE -- nobody holds GENE) not in MAINT.
      - Quantum: doc-test-05 (BankOne, score 25) not in feed (threshold 40).
- [ ] 6.2 Add group access check: for every item in every feed, assert the doc's
      group_guid is in the token's permitted groups. (May need to return group_guid
      in feed serialization if not already present.)
- [ ] 6.3 Run golden set -- false-positive tests pass.
- [ ] 6.4 Commit with message "P3: false positives guarded".

### Step 7 -- Add reason field assertions (P4)

Files: `simulation/scripts/validate_test_set.py`

- [ ] 7.1 For each MAINTENANCE item: assert reason contains at least one ticker from
      the client's holdings or watchlist (case-insensitive substring match).
- [ ] 7.2 For each OPPORTUNITY item: assert reason contains at least one theme from
      the client's mandate_themes (case-insensitive substring match).
- [ ] 7.3 Assert no item has an empty or None reason field.
- [ ] 7.4 Add "call script" line to report output: for each client, print
      "TOP CALL: {title} -- {reason}" using the top combined item.
- [ ] 7.5 Run golden set -- reason assertions pass.
- [ ] 7.6 Commit with message "P4: call script proven".

### Step 8 -- Add infrastructure guardrails (P5)

Files: `simulation/scripts/validate_test_set.py`, `simulation/run_avatar_simulation.sh`

- [ ] 8.1 Add pre-flight check in run_avatar_simulation.sh (--test-set path):
      after universe init but before inject, run probe_graph.py and assert
      zero Document nodes exist. Fail with clear message if dirty.
- [ ] 8.2 Add theme vocabulary gate: after injection, query all Document nodes'
      themes and all ClientProfile mandate_themes, assert every value is in
      VALID_THEMES from mandate_enrichment.py.
- [ ] 8.3 Add schema completeness check: every injected Document node must have
      non-null impact_score, impact_tier, themes, created_at.
- [ ] 8.4 Make --require-nonempty the default when --test-set is used.
- [ ] 8.5 Run golden set end to end from --reset -- all gates pass.
- [ ] 8.6 Commit with message "P5: infrastructure guardrails".

### Step 9 -- Full regression run and baseline save

- [ ] 9.1 Run full golden set from clean reset:
      `./simulation/run_avatar_simulation.sh --test-set --report-json tmp/golden-baseline.json --report-md tmp/golden-baseline.md`
- [ ] 9.2 Review the markdown report -- every KPI meets target.
- [ ] 9.3 Save baseline: `uv run simulation/scripts/golden_baseline.py save`
- [ ] 9.4 Tag commit as "avatar-feed-gap-plan-complete".
