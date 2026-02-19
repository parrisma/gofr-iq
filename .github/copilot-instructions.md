# Copilot Instructions for gofr-iq (succinct)

These rules are mandatory. If anything is unclear, ask before acting.

## Non-negotiables

- Ask when ambiguous. Do not assume intent or make product/design decisions.
- Show full terminal output. Do not use `head`, `tail`, or truncating pipes.
- ASCII only in code, logs, and docs. No emoji or Unicode symbols.
- Never use `localhost`. Use Docker service names on the gofr network (e.g., `gofr-vault`, `gofr-neo4j`).
- Python workflow uses UV only: `uv run`, `uv add`, `uv sync`. Do not use pip/venv workflows.
- Do not use `print()`. Use the project's `StructuredLogger`.
- Do not rewrite pushed git history. No `git commit --amend` or rebases for pushed commits; use follow-up commits.

## Default workflow

- Trivial fix (few lines, obvious): implement directly.
- Anything non-trivial: write a short spec first, get approval, then a stepwise plan, get approval, then execute.
  - Spec: WHAT/WHY + constraints + assumptions/questions (no code).
  - Plan: small verifiable steps + update code/docs/tests + run tests before/after.

## Environment and services

- Dev runs in a Docker dev container; prefer repo scripts to manage services.
- Vault is `http://gofr-vault:8201` (do not use `localhost` or `host.docker.internal` for Vault).
- Shared auth is managed by gofr-common; prefer its scripts over ad-hoc commands.

## Testing

- Always run tests via `./scripts/run_tests.sh` (never `pytest` directly).
- Do not skip failing tests. Fix the underlying issue.

## Logging and errors

- Log with `StructuredLogger` and include structured context (ids, urls, params, duration_ms).
- Errors must include: cause, context, recovery options.
- Add new error codes to `RECOVERY_STRATEGIES` in `app/errors/mapper.py` when applicable.
- Add a domain exception in `app/exceptions/` when a generic exception is not appropriate.

## MCP tool changes

If adding/modifying an MCP tool in `app/mcp_server/mcp_server.py`, follow this pattern:

1. Add the `Tool(...)` schema in `handle_list_tools` (inputSchema, description, annotations).
2. Add routing in `handle_call_tool`.
3. Implement `_handle_<tool_name>(arguments)` returning `List[TextContent]` via `_json_text(...)`.
4. Use `_error_response(...)` or `_exception_response(...)` for all error paths.

## Common scripts and auth (quick refs)

- Load Vault token + JWT secret: `source <(./lib/gofr-common/scripts/auth_env.sh --docker)`
- Manage groups/tokens: `./lib/gofr-common/scripts/auth_manager.sh --docker ...`
- Start/restart prod stack: `./scripts/start-prod.sh`
- Run tests: `./scripts/run_tests.sh`

