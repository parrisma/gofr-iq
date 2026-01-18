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
`simulation/run_simulation.sh` is the automated entrypoint that:
- Discovers required groups/sources from simulation config (universe builder, story generator)
- Creates groups and tokens in Vault automatically
- Registers sources in MCP registry
- Loads universe (companies, relationships, factors) to Neo4j
- Loads clients to Neo4j
- Generates stories with full metadata (or reuses cached stories to save time/cost)
- Ingests stories with validation gates

Example:
```bash
# Default: generates 10 stories (or reuses cached ones)
./simulation/run_simulation.sh --count 10

# Force regeneration even if cache exists
./simulation/run_simulation.sh --count 10 --regenerate

# Skip generation entirely, use existing files
./simulation/run_simulation.sh --skip-generate
```

**💰 Cost Savings**: By default, generated stories are cached and reused across resets. This saves OpenRouter API costs (~$2-5 per 10 stories) and time (~3-5 minutes). See [CACHING.md](./CACHING.md) for details.

All scripts use SSOT module (`lib/gofr_common/gofr_env.py`) for token access - no manual .env files needed.

## Tokens & Authentication
- Bootstrap tokens: `config/generated/bootstrap_tokens.json` (auto-created by bootstrap.py)
- All Python scripts import: `from lib.gofr_common.gofr_env import get_admin_token`
- Simulation tokens auto-created in Vault by run_simulation.sh
- Never commit real keys.

## References
- [CACHING.md](./CACHING.md) — document caching to save time and API costs
- [Synthetic Data Proposal](synthetic_data_proposal.md) — scenario design for stress cases.
