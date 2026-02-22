#!/bin/bash
# =============================================================================
# Full Reset + Generate + Ingest + Validate
# =============================================================================
# End-to-end script: wipes all data, regenerates everything from scratch,
# ingests with parallel workers, backfills client mandates, runs bias sweep.
#
# Usage:
#   ./scripts/full_reset_and_run.sh                  # defaults: 200 baseline, 3 workers
#   ./scripts/full_reset_and_run.sh --count 600      # 600 baseline stories
#   ./scripts/full_reset_and_run.sh --workers 5      # 5 ingest workers
#   ./scripts/full_reset_and_run.sh --skip-reset      # skip the destructive reset step
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# -- defaults ----------------------------------------------------------------
BASELINE_COUNT=200
WORKERS=3
SKIP_RESET=0
LAMBDAS="0,0.25,0.5,0.75,1"

# -- arg parsing -------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --count)      BASELINE_COUNT="$2"; shift 2 ;;
        --workers)    WORKERS="$2"; shift 2 ;;
        --lambdas)    LAMBDAS="$2"; shift 2 ;;
        --skip-reset) SKIP_RESET=1; shift ;;
        --help|-h)
            echo "Usage: $0 [--count N] [--workers N] [--lambdas 0,0.5,1] [--skip-reset]"
            exit 0
            ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

cd "${PROJECT_ROOT}"

# -- helpers -----------------------------------------------------------------
STEP=0
step() {
    STEP=$((STEP + 1))
    echo ""
    echo "======================================================================"
    echo "  STEP ${STEP}: $1"
    echo "======================================================================"
    echo ""
}

elapsed_since() {
    local start=$1
    local now
    now=$(date +%s)
    local secs=$((now - start))
    printf '%dm%02ds' $((secs / 60)) $((secs % 60))
}

die() { echo "FATAL: $*" >&2; exit 1; }

RUN_START=$(date +%s)

# -- load env ----------------------------------------------------------------
[[ -f docker/.env ]] || die "docker/.env not found. Run bootstrap first."
set -a; source docker/.env; set +a

# Bridge env var names if needed
export GOFR_IQ_NEO4J_PASSWORD="${GOFR_IQ_NEO4J_PASSWORD:-${NEO4J_PASSWORD:-}}"
export GOFR_IQ_NEO4J_URI="${GOFR_IQ_NEO4J_URI:-bolt://gofr-neo4j:7687}"

# =============================================================================
# STEP 1: Reset infrastructure
# =============================================================================
if [[ "${SKIP_RESET}" -eq 0 ]]; then
    step "Reset infrastructure (start-prod.sh --reset)"
    echo "yes" | ./docker/start-prod.sh --reset

    step "Validate schema (bootstrap_graph.py --validate-only)"
    uv run python scripts/bootstrap_graph.py --validate-only
else
    step "Skip reset (--skip-reset)"
    echo "Skipping destructive reset. Assuming infra is healthy."
fi

# =============================================================================
# STEP 2: Clear simulation output directories
# =============================================================================
step "Clear simulation output directories"
for d in simulation/test_output simulation/test_output_phase3 simulation/test_output_phase4; do
    if [[ -d "${d}" ]]; then
        count=$(find "${d}" -name 'synthetic_*.json' 2>/dev/null | wc -l)
        rm -f "${d}"/synthetic_*.json
        echo "  Cleared ${count} files from ${d}"
    else
        echo "  ${d} does not exist (nothing to clear)"
    fi
done

# =============================================================================
# STEP 3: Generate + ingest baseline stories
# =============================================================================
step "Generate + ingest ${BASELINE_COUNT} baseline stories (${WORKERS} workers)"
STEP_START=$(date +%s)
./simulation/run_simulation.sh \
    --count "${BASELINE_COUNT}" \
    --regenerate \
    --ingest-workers "${WORKERS}"
echo "  Baseline done in $(elapsed_since ${STEP_START})"

# =============================================================================
# STEP 4: Generate + ingest Phase 3 (defensive calibration)
# =============================================================================
step "Generate + ingest Phase 3 scenarios (${WORKERS} workers)"
STEP_START=$(date +%s)
./simulation/run_simulation.sh \
    --phase3 \
    --regenerate \
    --skip-universe --skip-clients \
    --ingest-workers "${WORKERS}" \
    --count 20
echo "  Phase3 done in $(elapsed_since ${STEP_START})"

# =============================================================================
# STEP 5: Generate + ingest Phase 4 (mandate/relationship needles)
# =============================================================================
step "Generate + ingest Phase 4 scenarios (${WORKERS} workers)"
STEP_START=$(date +%s)
./simulation/run_simulation.sh \
    --phase4 \
    --regenerate \
    --skip-universe --skip-clients \
    --ingest-workers "${WORKERS}" \
    --count 20
echo "  Phase4 done in $(elapsed_since ${STEP_START})"

# =============================================================================
# STEP 6: Backfill client mandate embeddings (handled by run_simulation.py
#          automatically, but verify)
# =============================================================================
step "Verify client mandate embeddings"
docker exec gofr-neo4j cypher-shell \
    -u neo4j -p "${NEO4J_PASSWORD}" \
    "MATCH (g:Group {name: 'group-simulation'})<-[:IN_GROUP]-(c:Client)-[:HAS_PROFILE]->(cp:ClientProfile)
     RETURN c.name AS name, size(cp.mandate_embedding) AS emb_dim, cp.mandate_themes IS NOT NULL AS has_themes
     ORDER BY name" 2>/dev/null

# =============================================================================
# STEP 7: Run bias sweep validation
# =============================================================================
step "Bias sweep (lambdas: ${LAMBDAS})"
STEP_START=$(date +%s)
uv run python simulation/validate_avatar_feeds.py \
    --bias-sweep \
    --lambdas "${LAMBDAS}"
echo "  Bias sweep done in $(elapsed_since ${STEP_START})"

# =============================================================================
# STEP 8: Counts summary
# =============================================================================
step "Final counts"
echo "  Neo4j documents:"
docker exec gofr-neo4j cypher-shell \
    -u neo4j -p "${NEO4J_PASSWORD}" \
    "MATCH (d:Document) RETURN count(d) AS doc_count" 2>/dev/null

echo "  ChromaDB entries:"
curl -s http://gofr-chromadb:8000/api/v1/collections | \
    python3 -c "
import sys, json, urllib.request
cols = json.load(sys.stdin)
for c in cols:
    resp = urllib.request.urlopen(f\"http://gofr-chromadb:8000/api/v1/collections/{c['id']}/count\")
    print(f\"    {c['name']}: {json.load(resp)}\")
"

echo "  Simulation files on disk:"
for d in simulation/test_output simulation/test_output_phase3 simulation/test_output_phase4; do
    count=$(find "${d}" -name 'synthetic_*.json' 2>/dev/null | wc -l)
    echo "    ${d}: ${count}"
done

# =============================================================================
# Done
# =============================================================================
echo ""
echo "======================================================================"
echo "  COMPLETE  (total: $(elapsed_since ${RUN_START}))"
echo "======================================================================"
