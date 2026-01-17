# Simulation & Synthetic Data

Use this folder to generate and ingest synthetic news for realistic testing of ingestion, graph extraction, and ranking.

## Why use it?
- Produce realistic, varied APAC-style stories to stress prompts and scoring.
- Validate ingestion + auth flows with group-scoped tokens.
- Exercise graph extraction, impact tiers, and hybrid search end-to-end.

## Quick use (happy path)
1) Start the stack (prod or dev) so Vault/Neo4j/Chroma are running.
2) Ensure you have valid tokens (see `docker/.vault-init.env` and `docker/.env`).
3) Generate stories:
```bash
uv run simulation/generate_synthetic_stories.py --help
```
4) Ingest stories:
```bash
uv run simulation/ingest_synthetic_stories.py --help
```
5) Verify: query via MCPO or tools and confirm groups are respected.

## Orchestrated run
`simulation/run_simulation.py` is the single entrypoint that can:
- Create required groups/tokens for simulation (apac_sales, us_sales, etc.)
- Generate `.env.synthetic` with fresh tokens
- Generate stories and ingest them

Example:
```bash
uv run simulation/run_simulation.py --count 30 --output simulation/test_output
```

## Tokens & env
- `simulation/.env.synthetic` (gitignored) holds synthetic tokens and options.
- `simulation/.env.openrouter` can hold a temporary OpenRouter key for generation.
- Never commit real keys.

## References
- [Synthetic Data Proposal](synthetic_data_proposal.md) — scenario design for stress cases.
