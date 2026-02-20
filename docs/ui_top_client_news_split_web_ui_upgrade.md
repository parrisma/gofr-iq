# Web UI upgrade: split shortlist vs. LLM why/summary

Goal: update the GOFR-IQ web UI to use the new two-step flow:
1) fast deterministic shortlist (no LLM)
2) on-demand LLM augmentation (why + summary)

This doc is written for an LLM/codegen agent implementing the UI changes.

## Background

Previously, the UI could treat `get_top_client_news` as “already enriched” (slow, could trigger multiple LLM calls).

Now the split is explicit:
- `get_top_client_news`: deterministic selection + ranking only (graph/ephemeral data). Returns a per-article `why_it_matters_base` (non-LLM).
- `why_it_matters_to_client`: LLM augmentation for ONE selected (client, document) pair. Returns:
  - `why_it_matters` (<= 30 words)
  - `story_summary` (<= 30 words)

UI must not assume shortlist results include LLM-generated text.

## API basics

- Base URL: `http://gofr-iq:8080`
- Tool endpoint: `POST /tools/{tool_name}`
- Auth: send `Authorization: Bearer <jwt>` header
  - Alternate: include `auth_tokens: ["<jwt>"]` in request body
- Response envelope:
  - Success: `{ "status": "success", "data": { ... }, "message": "..." }`
  - Error: `{ "status": "error", "error_code": "...", "message": "...", "recovery_strategy": "...", "details": { ... } }`

## Tool contracts (what the UI must call)

### 1) Shortlist: get_top_client_news

Tool: `POST /tools/get_top_client_news`

Request body:
```json
{
  "client_guid": "550e8400-e29b-41d4-a716-446655440000",
  "limit": 3,
  "time_window_hours": 24,
  "min_impact_score": null,
  "impact_tiers": null,
  "include_portfolio": true,
  "include_watchlist": true,
  "include_lateral_graph": true
}
```

Response `data` (shape):
```json
{
  "articles": [
    {
      "document_guid": "...",
      "title": "...",
      "created_at": "...",
      "impact_score": 75,
      "impact_tier": "GOLD",
      "affected_instruments": ["AAPL"],
      "relevance_score": 0.82,
      "reasons": ["DIRECT_HOLDING"],
      "why_it_matters_base": "Deterministic baseline explanation ..."
    }
  ],
  "total_count": 3,
  "filters_applied": {
    "time_window_hours": 24,
    "min_impact_score": 0.0,
    "impact_tiers": ["PLATINUM", "GOLD", "SILVER"],
    "include_portfolio": true,
    "include_watchlist": true,
    "include_lateral_graph": true
  }
}
```

Notes:
- This call is intended to be fast and safe to run on initial page load.
- The UI should render `why_it_matters_base` immediately (it is not LLM output).

### 2) Augmentation: why_it_matters_to_client

Tool: `POST /tools/why_it_matters_to_client`

Request body:
```json
{
  "client_guid": "550e8400-e29b-41d4-a716-446655440000",
  "document_guid": "..."
}
```

Response `data` (shape):
```json
{
  "client_guid": "...",
  "document_guid": "...",
  "why_it_matters": "<=30 words, client-specific",
  "story_summary": "<=30 words, story-only"
}
```

Notes:
- This call triggers an LLM request. It should NOT be called for large lists by default.
- It is best invoked only for selected items (e.g., user clicks/expands a story).

## Required UI behavior changes

1) Shortlist page
- Use `get_top_client_news` to populate the list.
- Render each item with:
  - title
  - created_at
  - impact tier/score
  - affected instruments (if present)
  - `why_it_matters_base`
- Do NOT attempt to render `why_it_matters` or `story_summary` at this stage.

2) Story details / enrichment
- When the user selects a story (exact trigger depends on existing UI; keep UX unchanged):
  - Call `why_it_matters_to_client(client_guid, document_guid)`.
  - Show a loading state for the enrichment region only.
  - On success, render:
    - `why_it_matters`
    - `story_summary`
- If enrichment fails, keep the shortlist item visible and show a non-blocking error near the enrichment region.

3) Caching (client, document)
- Cache augmentation results keyed by `(client_guid, document_guid)` in memory for the session.
- Do not re-call the LLM tool if the same story is re-opened.

## Error handling

Handle tool error envelopes (status == "error"):

Shortlist (`get_top_client_news`) common cases:
- `CLIENT_NOT_FOUND`: show “client not found” and route user to client selection/creation.
- `CLIENT_DEFUNCT`: show “client is defunct”.
- `QUERY_SERVICE_UNAVAILABLE` / `TOP_NEWS_RETRIEVAL_FAILED`: show a generic retry UI.

Augmentation (`why_it_matters_to_client`) common cases:
- `LLM_SERVICE_UNAVAILABLE`: show “LLM not configured” (do not block shortlist).
- `WHY_IT_MATTERS_FAILED`: show a retry button for the enrichment region.

Never log or display JWTs or API keys.

## Acceptance criteria (for review)

- Shortlist loads without triggering any LLM calls.
- Selecting a story triggers exactly one LLM call for that story.
- The UI shows deterministic `why_it_matters_base` immediately, then replaces/augments with LLM output only after `why_it_matters_to_client` returns.
- Re-opening the same story does not re-call `why_it_matters_to_client` (session cache).
- Errors from enrichment do not break the shortlist view.
