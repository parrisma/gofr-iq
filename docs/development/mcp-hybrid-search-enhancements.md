# MCP Hybrid Search Enhancements (Parking Lot)

Purpose: capture proposed improvements to the MCP-facing hybrid search API (`query_documents`) so we can implement them later.

## Goals
- Improve LLM ergonomics and explainability for hybrid (semantic + graph) search
- Strengthen filter/recency/trust controls
- Add pagination and clearer response contracts
- Provide discoverability of allowed filter values

## Proposed Enhancements

### 1) Pagination & Counts
- Add `offset` or `page_token` to `query_documents` to avoid large `n_results`
- Return `total_semantic_found` and `total_graph_found` separately for transparency

### 2) Response Contract (Explainability)
- Standard fields: `source_name`, `impact_tier`, `impact_score`, `discovered_via`, `created_at`
- Add `graph_paths`: array of `{via, via_doc}` for graph-discovered items
- Add `expanded_from`: semantic doc GUID that seeded the graph hop
- Optional `rationale`: one-line explanation the UI/LLM can surface

### 3) Filters & Defaults
- Set explicit default for `impact_tiers` to avoid over-broad searches
- Convenience recency filter: `since_days` (derives `date_from`)
- Add `trust_floor` to drop unverified/low-trust sources when needed

### 4) Personalization Signals
- If `client_guid` is provided, return `matched_holdings` (tickers) for relevance narration
- Optional `personalization_strength` to tune bias toward portfolio/watchlist items

### 5) Graph Expansion Controls
- Expose `max_expansion` and `graph_expansion_depth` as bounded params for predictability

### 6) Facet Discovery Tool
- New MCP tool `list_facets` to return allowed values:
  - regions, sectors, event_types, impact_tiers definitions
  - helps LLM propose valid filters

### 7) Tool UX
- Slim tool descriptions; add a short "When to use" and a minimal param table in the system prompt
- Provide 2–3 canned call templates in the prompt (high-impact sector query, client-personalized query, graph-explainable query)

## Next Steps (when prioritized)
1) Design API changes: params (`offset`, `since_days`, `trust_floor`, graph controls) and response schema (`graph_paths`, `expanded_from`, counts)
2) Implement in `app/services/query_service.py` and `app/tools/query_tools.py`; update tests
3) Add `list_facets` tool to `app/tools` and expose via MCP
4) Update OpenWebUI system prompt with new call templates and fields
5) Ship docs: `docs/features/hybrid-search.md` + OpenWebUI usage notes
