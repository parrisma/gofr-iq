# UI LLM Note: Client Profile Completeness Score (CPCS)

## Purpose
The CPCS provides a **0.0–1.0** readiness score for each client profile. It is a **baseline quality metric** to show how complete the profile is before interpreting or ranking news. This allows Sales/Trading to see improvement as Phase 1 and Phase 2 enrich the profile.

## Why it matters
- **Explains coverage quality**: Low score indicates missing inputs that hurt ranking relevance.
- **Guides next actions**: Shows gaps that should be filled first (holdings, mandate, constraints, engagement).
- **Tracks improvement**: The score should increase as fields/relationships are populated.

## What’s implemented
### 1) MCP tool: `get_client_profile_score`
Returns:
- `score` (0–1)
- `breakdown` with per-section scores and weights
- `missing_fields` list for clear action steps

### 2) MCP tool: `list_clients`
New options:
- `include_completeness_score` (bool)
- `min_completeness_score` (float 0–1)
- `sort_by_completeness` (bool, desc)

## UI guidance
### Primary UI placements
1. **Client 360 Header**
   - Show a progress bar with the CPCS.
   - Label: “Profile Completeness”.
   - Tooltip: “Measures data readiness to serve this client (0–1).”

2. **Client List / Book View**
   - Add optional column “Completeness Score”.
   - Support sorting and filtering (e.g., show score < 0.5).
   - Quick action: “See missing fields”.

3. **Profile Gaps Panel**
   - Display `missing_fields` as checklist items.
   - Each item should link to the relevant edit field.

### How to use in UX flows
- **Before generating feed**: If score < 0.5, show a soft warning: “Low profile completeness may reduce relevance.”
- **Onboarding**: Use score to guide step completion; confirm score improvement after data entry.
- **Sales review**: Prioritize outreach or data cleanup by sorting low scores.

## Functional behavior (must not change)
- **Holdings (35%)**: Score is 1.0 if there are positions or watchlist items.
- **Mandate (35%)**: 0.33 each for `mandate_type`, `benchmark`, `horizon`.
- **Constraints (20%)**: 1.0 if `esg_constrained` is set (true/false).
- **Engagement (10%)**: 1.0 if both `primary_contact` and `alert_frequency` exist.

## Avoids schema changes
This feature only reads existing fields/relationships and is designed for Phase 1 rollout.

## UX copy suggestions
- “Completeness: 0.67 — Good. Add benchmark to improve.”
- “Completeness: 0.33 — Missing holdings/watchlist and mandate fields.”
- “Low completeness can reduce idea relevance.”

## API hostnames
When referencing services, use container hostnames (e.g., `gofr-iq-mcp`) rather than `localhost`.
