# gofr-iq validation narrative (sales + traders)

Date: 2026-02-22
Scope: Validation Protocol steps 0-2 (reset/bootstrap, infrastructure readiness, LLM key validation)

## Why this matters
Before we can claim "the system matches stories to a client profile", we need to prove the platform services that power ingestion + ranking are reachable and authenticated.

## Step 0: Clean baseline (reset and bootstrap)

What we will run:
- `./docker/start-prod.sh --reset` (or `--nuke` if that is the chosen reset flag)
- `./docker/manage-infra.sh status`
- `uv run scripts/bootstrap_graph.py --validate-only`

What we ran (this session):
- `./docker/start-prod.sh --nuke`
- Service confirmation: `docker ps | grep gofr-...`
- Graph validation: `set -a; source lib/gofr-common/config/gofr_ports.env; source docker/.env; set +a; uv run scripts/bootstrap_graph.py --validate-only`

Expected evidence:
- Services restart cleanly with a fresh dataset (repeatable starting point)
- Health check reports required services are `healthy`
- Graph schema and core taxonomy are present (constraints/indexes + Region/Sector/EventType/Factor nodes)

Evidence captured:
- Containers running and healthy: gofr-neo4j, gofr-chromadb, gofr-vault, gofr-iq-mcp, gofr-iq-mcpo, gofr-iq-web
- Graph bootstrap validation passed:
	- Constraints: 25 (>= 23)
	- Indexes: 35 (>= 11)
	- Region/Sector/EventType/Factor nodes all met expected minimum counts

## Step 1: Infrastructure and secret readiness

What we ran:
- `./simulation/run_simulation.sh --validate-only`

Run artifact:
- Log file: `simulation/run_logs/run_20260222_100335.log`

Evidence (from command output):
- Neo4j reachable at `bolt://gofr-neo4j:7687`
- ChromaDB responding at `gofr-chromadb:8000`
- Vault responding at `http://gofr-vault:8201`
- Simulation gates passed: `auth`, `sources`, `universe`, `clients`

Interpretation for traders:
- Neo4j is the "relationship and client profile" engine.
- ChromaDB is the "semantic retrieval" engine.
- Vault is the "secrets and auth" backbone.
- With all three reachable and the gates passing, the system is in a known-good state to run the story-to-client matching validation steps that follow.

Notes / follow-ups:
- The `--validate-only` run also performed some simulation bootstrapping (sources, universe, clients). That is OK for now, but later steps should record whether we were validating an existing dataset vs creating a fresh one.

Engineering notes (not customer-facing):
- The run emitted a Neo4j warning about the `mandate_embedding` property key not existing yet, but the run continued and completed the gates successfully.

Engineering notes (operational):
- `scripts/bootstrap_graph.py` requires `NEO4J_PASSWORD` (or `GOFR_IQ_NEO4J_PASSWORD`) in the environment. After a prod bootstrap, source `docker/.env` before running it manually.

## Step 2: LLM key is active (embedding + chat)

What we ran:
- `GOFR_IQ_RUN_LLM_INTEGRATION_TESTS=1 ./scripts/run_tests.sh -k "integration_llm" -v`

Evidence captured:
- 12 passed, 0 failed, 898 deselected (53.86s)
- Chat completion: simple chat, system messages, JSON extraction, multi-turn -- all passed
- Embeddings: single, batch, similarity, factory function, dimensions check -- all passed

Interpretation for traders:
- The LLM service (powers story extraction and semantic matching) is confirmed working end-to-end.
- Both the "understanding" path (chat completion for entity extraction from news) and the "matching" path (embedding generation for finding similar stories/mandates) are live.

Engineering notes (not customer-facing):
- Initial runs failed with 401 "User not found" from OpenRouter.
- Root cause: docker/.env contained a stale API key (suffix ...731e0e9e) that authenticated for read-only /models but was rejected for /chat/completions. Vault had the correct key (suffix ...1649ee0e).
- Fix: synced docker/.env, lib/gofr-common/.env, and secrets/llm_api_key to the Vault-authoritative value.
- Lesson: Vault is the SSOT for the OpenRouter key. Any local .env file that diverges will cause silent failures only on write endpoints.
