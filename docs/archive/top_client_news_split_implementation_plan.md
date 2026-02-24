# Implementation Plan: Split `get_top_client_news` into Selection + LLM Augmentation

Owner: Sales Trading / Engineering
Date: 2026-02-20
Status: Draft (ready for execution)

This plan implements the proposal in docs/top_client_news_split_proposal.md.

## Guiding principles

- Keep selection deterministic and fast (no LLM calls).
- Keep augmentation optional and bounded (1 completion per (client, doc) or small batch later).
- Preserve current access-control behavior (permitted groups from JWTs).
- Maintain backward compatibility until callers migrate.
- Prefer small, verifiable steps with targeted tests.

## Baseline (before changes)

Run targeted tests so we can detect regressions:

- `./scripts/run_tests.sh -k "get_top_client_news" -v`

Optionally capture a timing sample on a realistic dataset (manual):

- call `get_top_client_news` once via MCP and note wall time

## Step 1: Introduce a selection-only service method (no LLM)

Goal: make the selection/ranking logic callable without any LLM-related behavior.

Changes:

1) In app/services/query_service.py
   - Extract selection logic from `get_top_client_news` into a new method, e.g.:
     - `get_top_client_news_selection(...) -> list[dict[str, Any]]`
   - This method must:
     - NOT accept `llm_service`
     - NOT call `_build_client_query_text` with LLM rewrite
     - NOT call `_build_why_it_matters` with LLM
     - Use only graph + stored metadata
   - Keep output shape aligned with existing `get_top_client_news` results, but allow an extra deterministic field:
     - `why_it_matters_base` (optional)

2) Decide on “graph/ephemeral only” semantics:
   - Default: graph candidates only (holdings/watchlist/benchmark/lateral)
   - Optional flag (explicit): include semantic candidates if needed (defer unless required)

Tests:

- Add new tests in test/test_query_service.py:
  - `test_get_top_client_news_selection_no_graph_index_returns_empty`
  - `test_get_top_client_news_selection_is_deterministic`
  - `test_get_top_client_news_selection_output_shape`

Verification:

- `./scripts/run_tests.sh -k "top_client_news_selection" -v`

## Step 2: Wire Tool 1: `get_top_client_news` to selection-only

Goal: re-scope the existing MCP tool name `get_top_client_news` to return selection-only results.

Changes:

1) In app/tools/client_tools.py
   - Update tool implementation to call `query_service.get_top_client_news_selection(...)`.
   - Preserve existing args and default behavior where possible.
   - Preserve access control:
     - still `resolve_permitted_groups` -> `get_group_uuids_by_names`.
   - Keep response keys stable for callers:
     - `articles`, `total_count`, `filters_applied`
   - Ensure `why_it_matters` field is either:
     - not present (preferred, since Tool 2 owns it), OR
     - present as deterministic base (if keeping shape identical is required)
   - Recommendation: include deterministic `why_it_matters_base` and keep `why_it_matters` omitted to force explicit augmentation.

2) Deprecation messaging (lightweight):
   - Update tool description string to clarify it is selection-only.

Tests:

- Update existing tool tests in test/test_client_tools.py:
  - Adjust expectations for `why_it_matters` field (remove or rename to `why_it_matters_base`).
  - Add a test that asserts the tool does not trigger any LLM calls.
    - Use a stubbed/mocked `llm_service` and assert call count == 0.

Verification:

- `./scripts/run_tests.sh -k "TestGetTopClientNews" -v`

## Step 3: Add Tool 2: `why_it_matters_to_client`

Goal: add a new MCP tool that takes (client_guid, document_guid) and returns two <=30 word strings.

Changes:

1) In app/tools/client_tools.py
   - Register new `@mcp.tool(name="why_it_matters_to_client", ...)`.
   - Inputs:
     - `client_guid: str`
     - `document_guid: str`
     - `auth_tokens: list[str] | None = None`
   - Output:
     - `why_it_matters: str` (<=30 words)
     - `story_summary: str` (<=30 words)
   - Enforce group visibility:
     - verify client in permitted groups
     - verify document is accessible under permitted groups (same model as query tool)

2) In app/services/query_service.py (or a new small service)
   - Implement a helper that:
     - fetches client context (profile, holdings, watchlist, benchmark, restrictions)
     - fetches document context (title, body if present, metadata/entities)
     - builds a single prompt
     - calls `llm_service.chat_completion(..., json_mode=True, temperature low)`
     - validates JSON output
     - validates <=30 words constraints
       - if over limit: retry once with stricter instruction OR truncate deterministically
     - returns the two strings

Notes:

- Keep the prompt strict: “no invention”, “use only provided text/context”.
- Use JSON mode to reduce parsing failures.

Tests:

- Add tests in test/test_client_tools.py:
  - success path returns both fields
  - enforces word limits (simulate overlong LLM response)
  - access control (document not in permitted group -> error)
- Add tests in test/test_query_service.py (if helper lives there):
  - prompt builder includes required context
  - parser rejects invalid JSON

Verification:

- `./scripts/run_tests.sh -k "why_it_matters_to_client" -v`

## Step 4: Performance validation

Goal: demonstrate the speed improvement and bounded LLM calls.

Measurements (manual or logged):

- Selection-only p50/p95 for `get_top_client_news`.
- LLM augmentation call count and latency for 3 documents.

Acceptance criteria:

- `get_top_client_news` selection completes without any chat completions.
- `why_it_matters_to_client` performs exactly one completion per call.

## Step 5: Documentation updates

- Update the tool documentation (docs/mcp-tool-interface.md) to reflect:
  - `get_top_client_news` is selection-only (graph/ephemeral only)
  - `why_it_matters_to_client` is the LLM augmentation tool

## Test plan summary (commands)

- Targeted:
  - `./scripts/run_tests.sh -k "get_top_client_news" -v`
  - `./scripts/run_tests.sh -k "why_it_matters_to_client" -v`

- Full suite (before merge):
  - `./scripts/run_tests.sh --coverage`

## Rollout plan

- Merge in steps (or feature-flag Tool 2 if needed).
- Update any client UI/agent to:
  - call Tool 1 for shortlist
  - call Tool 2 only for displayed items
