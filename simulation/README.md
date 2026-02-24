# gofr-iq simulation

## Purpose

Populate a self-contained graph/vector dataset (universe, clients, documents) and
validate that gofr-iq routes valuable documents to the right client profiles while
filtering noise.

Two complementary modes exist:

1. Deterministic "golden set" tests -- high-certainty regression signal.
2. LLM-driven synthetic generation + ingestion -- end-to-end realism and
   extraction stress-testing.


## What the simulation proves

### Avatar feed (2-channel model)

validate_avatar_feeds.py queries the real MCP get_avatar_feed tool for every
simulation client and asserts:

1. MAINTENANCE channel contains items affecting client holdings or watchlist.
2. OPPORTUNITY channel contains items matching mandate themes.
3. OPPORTUNITY items do NOT overlap with the client's current position tickers.
4. No document appears in both channels (deduplication).
5. All items have required fields (document_guid, title, channel, relevance_score).
6. Combined list is sorted by relevance_score descending.

### Classic feed routing

validate_feeds.py proves 6 graph-traversal behaviors:

1. Direct portfolio relevance -- documents affecting holdings surface.
2. Supply chain propagation -- supplier/customer impacts traverse 1-hop.
3. Competitor awareness -- competitive intel surfaces via COMPETES_WITH (2-hop).
4. Macro factor exposure -- factor-level events reach exposed holdings.
5. Trust gating -- conservative clients filter unreliable sources.
6. Zero false positives -- documents never appear in irrelevant feeds.


## Prerequisites

- Production infrastructure running: Neo4j, Vault, MCP server, ChromaDB.
- UV available on PATH.
- OpenRouter API key stored in Vault at gofr/config/api-keys/openrouter.
- Run from repo root (not simulation/).

Start infrastructure if not running:

  ./docker/start-prod.sh


## Full simulation run (recommended sequence)

### Step 1 -- bootstrap platform (first time only)

  ./scripts/bootstrap.sh

### Step 2 -- run the full simulation (200 documents, production data)

This single command covers: auth setup, source registration, universe load,
client generation + mandate embedding backfill, story generation, and
parallel ingestion.

  ./simulation/run_avatar_simulation.sh --count 200 --report-json tmp/avatar_uat.json --report-md tmp/avatar_report.md

The script pipeline is:
  1. ./docker/start-prod.sh --reset   (tear down all data)
  2. ./simulation/run_simulation.sh   (auth, universe, clients, generate, ingest)
  3. uv run simulation/validate_avatar_feeds.py

### Step 3 -- golden set regression

  ./scripts/run_golden_baseline.sh --validate

To save current results as the new baseline:

  ./scripts/run_golden_baseline.sh


## run_simulation.sh (lower-level entry point)

Thin wrapper around run_simulation.py. Emits a per-run log to
simulation/run_logs/.

  ./simulation/run_simulation.sh --count 50                     # generate + ingest 50 docs
  ./simulation/run_simulation.sh --ingest-only                  # reuse cached JSONs, ingest only
  ./simulation/run_simulation.sh --count 50 --regenerate        # force-regenerate and ingest
  ./simulation/run_simulation.sh --validate-only                # setup only (no docs)
  ./simulation/run_simulation.sh --phase3 --regenerate          # Phase3 calibration injection
  ./simulation/run_simulation.sh --phase4 --regenerate          # Phase4 calibration injection
  ./simulation/run_simulation.sh --refresh-timestamps           # refresh published_at in cached JSONs
  ./simulation/run_simulation.sh --count 50 --ingest-workers 5  # parallel ingestion (5 workers)

Key flags:

  --count N               Stories to generate (default: 10)
  --output DIR            Output directory (default: simulation/test_output)
  --regenerate            Force new generation even if cached files exist
  --ingest-only           Skip generation, reuse existing JSONs
  --skip-generate         Alias for --ingest-only
  --skip-ingest           Skip ingestion stage
  --validate-only         Auth/source/universe setup only (count=0)
  --phase3                Inject Phase3 calibration scenarios (exclusive with --phase4)
  --phase4                Inject Phase4 calibration scenarios (exclusive with --phase3)
  --skip-universe         Skip loading companies/relationships to Neo4j
  --skip-clients          Skip generating/loading clients to Neo4j
  --init-groups-only      Create/verify auth groups then stop
  --init-tokens-only      Create/verify groups + tokens then stop
  --refresh-timestamps    Rewrite published_at in JSONs so docs are recent; then exit
  --spread-minutes N      Window for timestamp spreading (default: 60)
  --ingest-workers N      Parallel ingestion workers (default: 1; 3-5 for speed)
  --backfill-mandate-embeddings / --no-backfill-mandate-embeddings
                          Embed mandate_text for simulation clients (default: on)
  --model MODEL           LLM model name for generation
  --openrouter-key KEY    OpenRouter key override (Vault is SSOT)
  --verbose               Verbose ingestion output

Recovery hints:
- Generation failed partway: rerun WITHOUT --regenerate to resume from cache.
- Ingestion failed partway: rerun with --ingest-only (same --output).
- Clean slate: delete output directory contents then rerun.


## Simulation pipeline (run_simulation.py internals)

Stage gates (each must pass before the next stage starts):

  auth         Groups and tokens created and verified in Vault.
  sources      NewsSource nodes registered in Neo4j.
  universe     Company graph (tickers, relationships, factors, exposures) loaded.
  clients      Synthetic clients + ClientProfile nodes loaded; mandate embeddings backfilled.
  generation   Synthetic story JSONs written to output dir.
  ingestion    Documents extracted, embedded, and wired in Neo4j + ChromaDB.

Auth tokens for the run are saved to simulation/tokens.json (treat as sensitive).


## Validation scripts

  uv run simulation/validate_avatar_feeds.py              # avatar 2-channel model
  uv run simulation/validate_feeds.py --verbose           # classic feed routing (6 behaviors)
  uv run simulation/validate_simulation.py                # general sanity checks


## Resetting the environment

Soft reset (wipes Neo4j, ChromaDB, storage; rebuilds clean):

  ./simulation/reset_simulation_env.sh

Full reset via production compose (destructive):

  ./docker/start-prod.sh --reset


## Refreshing stale document timestamps

When cached synthetic JSONs are old enough to fall outside feed time windows,
refresh their published_at values before ingesting:

  ./simulation/run_simulation.sh --refresh-timestamps
  # then
  ./simulation/run_simulation.sh --ingest-only --count 200 --ingest-workers 3


## Phase3 and Phase4 calibration modes

Phase3 and Phase4 inject specific calibration scenarios from the SCENARIOS list
in generate_synthetic_stories.py. They write to separate directories
(simulation/test_output_phase3, simulation/test_output_phase4) and run a
post-ingest calibration sanity check.

  ./simulation/run_simulation.sh --phase3 --regenerate --skip-universe --skip-clients
  ./simulation/run_simulation.sh --phase4 --regenerate --skip-universe --skip-clients

--phase3 and --phase4 are mutually exclusive.


## Mandate embedding backfill

Mandate embeddings are computed automatically during a full run (controlled by
--backfill-mandate-embeddings, which is on by default). To run backfill
standalone against an existing Neo4j dataset:

  uv run python scripts/backfill_client_mandates.py --group-name group-simulation --limit 200


## Directory structure

  simulation/
    run_simulation.sh           Main entry point (wrapper)
    run_simulation.py           Orchestrator (auth, data, generate, ingest, gates)
    run_avatar_simulation.sh    End-to-end UAT pipeline (reset -> run -> validate)
    reset_simulation_env.sh     Soft reset
    generate_synthetic_clients.py  Client generator
    generate_synthetic_stories.py  LLM story generator (SCENARIOS, CLIENT_PORTFOLIOS)
    ingest_synthetic_stories.py    Ingestion via manage_document tooling
    load_simulation_data.py        Universe + client Neo4j loader
    validate_avatar_feeds.py       Avatar feed (2-channel) assertions
    validate_feeds.py              Classic feed routing assertions (6 behaviors)
    validate_simulation.py         General sanity checks
    query_client_feed.py           Direct Neo4j feed inspector
    check_documents.py / check_cache.py  Ad-hoc diagnostics
    universe/                      Universe topology builder
    tokens.json                    Minted run tokens (sensitive, gitignored)
    test_output/                   Cached synthetic story JSONs (main)
    test_output_phase3/            Cached Phase3 calibration JSONs
    test_output_phase4/            Cached Phase4 calibration JSONs
    run_logs/                      Per-run log files


## Network and tooling

- All services accessed via Docker service names on gofr-net.
  - Neo4j:     bolt://gofr-neo4j:7687
  - Vault:     http://gofr-vault:8201
  - ChromaDB:  gofr-chromadb:8000
- Never use localhost or 127.0.0.1.
- UV only; no pip.
- OpenRouter API key is the Vault SSOT; env var GOFR_IQ_OPENROUTER_API_KEY is
  the fallback for non-Vault contexts.
