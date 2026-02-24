# Proposal: Split `get_top_client_news` into Selection + LLM Augmentation

Owner: Sales Trading / Engineering
Date: 2026-02-20
Status: Draft (for review)

## Executive summary

Today `get_top_client_news` combines two distinct responsibilities:

1) Selecting and ranking candidate stories for a client (deterministic, graph/index driven).
2) Generating human-readable explanation/summaries (non-deterministic, LLM-driven).

In production this coupling creates minutes-long tail latency, variable cost, and the operational risk that LLM/provider issues degrade the core “top news” experience.

This proposal splits the capability into two tools:

- `get_top_client_news`: fast, deterministic, “graph/ephemeral only” selection and ranking.
- `why_it_matters_to_client`: optional LLM augmentation for a specific (client, document) pair, returning:
  - <= 30 words: why this story matters to this client
  - <= 30 words: summary of the story

This split preserves the current user outcome while improving latency, cost control, reliability, and auditability.

## Problem statement

Observed issue: `get_top_client_news` can take minutes.

Root cause (high level): it can trigger multiple chat completions per request (query rewrite + per-candidate “why it matters” generation), turning a “top 3 items” request into dozens of sequential LLM calls.

Additional issues from coupling:

- Reliability: selection becomes dependent on LLM availability.
- Cost: spend scales with candidate count, not with requested output.
- Observability: difficult to isolate selection latency vs LLM latency.
- UX: hard to stream results; user waits for the LLM even to see the shortlist.

## Goals

- Keep “top news selection” fast and dependable (seconds, not minutes).
- Make LLM augmentation optional and on-demand.
- Bound LLM call count to user intent (usually 1-3 items).
- Preserve access control: group-based visibility must apply to both steps.
- Maintain backward compatibility (short term) and provide a clean migration path.

## Non-goals

- Redesign the scoring model or ranking weights beyond what is needed for the split.
- Add new UI flows or product features.
- Introduce new external infra.

## Current behavior (summary)

`get_top_client_news` currently:

- Loads client profile context, holdings, watchlist, benchmark, ESG exclusions.
- Builds graph candidates from Neo4j relations:
  - Direct holdings (highest boost)
  - Watchlist / benchmark
  - Optional lateral expansion (competitors, suppliers, peers)
- Builds semantic candidates via hybrid search (embedding similarity) and merges.
- Applies time-window and ESG exclusion filtering.
- Computes a final relevance score combining semantic + graph + impact + recency.
- Optionally uses LLM to rewrite the semantic query and/or generate “why it matters”.

The selection/ranking is valuable and should be kept deterministic by default.

## Proposal

### Tool 1: `get_top_client_news` (Selection / deterministic)

Purpose: return a ranked shortlist of candidate stories for a given client using ONLY persisted graph/index/metadata.

Key properties:

- Deterministic: no chat completions.
- Fast: one pass to build candidate set + rank.
- Auditable: scoring inputs are stored and explainable.

Data sources allowed:

- Neo4j graph relations and stored node/edge properties.
- Document metadata already stored at ingest time (impact, tickers, entities, themes, created_at, source).
- Client profile fields stored in graph (mandate_type, horizon, restrictions JSON, ESG flags).

Data sources NOT used:

- LLM calls (no prompt rewrite, no summarization).
- New embeddings generation at query time.

Suggested response payload (example; aligns with existing output shape where possible):

```json
{
  "client_guid": "...",
  "time_window_hours": 24,
  "articles": [
    {
      "document_guid": "...",
      "title": "...",
      "created_at": "...",
      "impact_score": 85,
      "impact_tier": "GOLD",
      "affected_instruments": ["AAPL", "TSM"],
      "relevance_score": 0.83,
      "reasons": ["DIRECT_HOLDING", "WATCHLIST"],
      "why_it_matters_base": "DIRECT_HOLDING, WATCHLIST impacting AAPL, TSM."
    }
  ]
}
```

Notes:

- `why_it_matters_base` is optional but useful as a deterministic fallback.
- The tool returns enough metadata for downstream enrichment, caching, and UI.

### Tool 2: `why_it_matters_to_client` (LLM augmentation)

Purpose: given a specific (client, document) pair, generate two short outputs:

1) `why_it_matters` (<= 30 words): why this story matters to this specific client.
2) `story_summary` (<= 30 words): a concise summary of the story.

Key properties:

- Optional: called only when needed.
- Bounded cost: one completion per (client, document), or a small batch.
- Strict constraints: no invented facts; word limits enforced.

Inputs:

- `client_guid`
- `document_guid`
- Optional: `style` (e.g., "sales trader" vs "PM") if needed later
- Auth/group context (same pattern as other tools)

Data retrieval:

- Client context: profile, holdings, watchlist, benchmark, restrictions, horizon, ESG.
- Document context: title, body (if available), entities/tickers/themes, impact score/tier, created_at/source.

Output payload:

```json
{
  "client_guid": "...",
  "document_guid": "...",
  "why_it_matters": "<=30 words",
  "story_summary": "<=30 words"
}
```

#### Prompt requirements

Single completion should return both fields.

Constraints:

- “Do not invent facts.”
- “Use only the provided client context and story text.”
- Word limits are hard constraints.
- Prefer JSON mode to simplify parsing.

Example prompt skeleton:

1) System: tool intent and hard rules.
2) User: structured context payload with:
   - client_profile
   - holdings/watchlist/benchmark
   - restrictions
   - document_title/body
   - extracted entities/tickers
3) Required output JSON:
   - why_it_matters
   - story_summary

## Performance and reliability impact

Expected improvements:

- p95 latency: “top news selection” becomes independent of LLM and should be seconds.
- LLM spend: bounded by explicit enrichment calls (often 1-3 items).
- Failure modes:
  - If LLM fails, the shortlist still works.
  - UI can show base reasons immediately and enrich as available.

## Caching strategy

Recommended caching keys:

- `get_top_client_news`:
  - Key: (client_guid, permitted_groups_hash, time_window_hours, min_impact, tiers, include_portfolio/watchlist/lateral)
  - TTL: 30-120 seconds

- `why_it_matters_to_client`:
  - Key: (client_guid, client_profile_version, document_guid, document_version)
  - TTL: longer (hours/days) depending on how frequently profiles/docs change

## Access control

Both tools must:

- Resolve permitted groups from auth tokens.
- Enforce that the client and document are accessible in those groups.
- Avoid leaking document content across groups in the LLM prompt.

## Migration plan

Phase 0 (Immediate):

- Keep existing `get_top_client_news` tool operational.
- Introduce the new `why_it_matters_to_client` tool.

Phase 1 (Adoption):

- Update UI/agent flows:
  - Call `get_top_client_news` to get shortlist.
  - Call `why_it_matters_to_client` only for the top N shown to user.

Phase 2 (Deprecation):

- Optionally re-scope the legacy tool to deterministic-only and/or mark LLM enrichment as deprecated.

## Risks and mitigations

- Risk: Users expect `why_it_matters` to always be present.
  - Mitigation: include deterministic `why_it_matters_base` in selection response; UI can show it while enrichment runs.

- Risk: LLM prompt may leak restricted context.
  - Mitigation: enforce group checks before fetching/including document text; include only minimal required context.

- Risk: Word limits not strictly enforced.
  - Mitigation: JSON mode + validation; if over limit, retry with stricter instruction or truncate deterministically.

## Open questions

1) Should `why_it_matters_to_client` support batching (list of document_guids) from day one?
2) Should `get_top_client_news` remove semantic search entirely (graph-only) or keep it behind an explicit flag?
3) Should we persist `why_it_matters`/`story_summary` back to storage for reuse, or cache only in-memory?
