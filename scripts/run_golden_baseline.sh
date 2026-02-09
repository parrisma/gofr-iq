#!/bin/bash
# =============================================================================
# Golden Baseline Runner
# =============================================================================
# Runs the golden set validation against production infrastructure and saves
# the results as the new golden baseline.
#
# Usage:
#   ./scripts/run_golden_baseline.sh              # Run + save baseline
#   ./scripts/run_golden_baseline.sh --diff       # Run + diff against saved baseline
#   ./scripts/run_golden_baseline.sh --show       # Show saved baseline
#   ./scripts/run_golden_baseline.sh --validate   # Run only (no save, no diff)
#
# Requirements:
#   - Production infra running (gofr-neo4j, gofr-vault, etc.)
#   - Golden set data loaded (run simulation first if needed)
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Output files
RESULTS_JSON="tmp/golden-baseline-v2.json"
RESULTS_MD="tmp/golden-baseline-v2.md"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Parse args
MODE="save"  # default: run + save
while [[ $# -gt 0 ]]; do
    case "$1" in
        --diff)
            MODE="diff"
            shift
            ;;
        --show)
            MODE="show"
            shift
            ;;
        --validate|--run)
            MODE="validate"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Runs golden set validation against production infrastructure."
            echo ""
            echo "Options:"
            echo "  (default)      Run validation, save as new golden baseline"
            echo "  --diff         Run validation, compare against saved baseline"
            echo "  --validate     Run validation only (no save, no diff)"
            echo "  --show         Show saved golden baseline (no run)"
            echo "  --help, -h     Show this help"
            echo ""
            echo "Examples:"
            echo "  $0                  # After code changes: run + save new baseline"
            echo "  $0 --diff           # Before release: check for regressions"
            echo "  $0 --validate       # Quick check: just run the tests"
            echo "  $0 --show           # Inspect: what's in the saved baseline"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}" >&2
            echo "Run $0 --help for usage" >&2
            exit 1
            ;;
    esac
done

# Handle --show (no infra needed)
if [ "$MODE" = "show" ]; then
    uv run python simulation/scripts/golden_baseline.py show
    exit $?
fi

# =============================================================================
# Load environment
# =============================================================================
echo -e "${BLUE}=== Golden Baseline Runner ===${NC}"

# Load Neo4j password from docker/.env (production)
DOCKER_ENV="${PROJECT_ROOT}/docker/.env"
if [ -f "$DOCKER_ENV" ]; then
    set -a
    source "$DOCKER_ENV"
    set +a
else
    echo -e "${RED}ERROR: docker/.env not found. Is production infra set up?${NC}" >&2
    echo "Run ./scripts/start-prod.sh first." >&2
    exit 1
fi

# Set Neo4j connection (production)
export GOFR_IQ_NEO4J_URI="bolt://gofr-neo4j:7687"
export GOFR_IQ_NEO4J_PASSWORD="${NEO4J_PASSWORD}"

# Verify Neo4j is reachable
echo -n "Checking Neo4j... "
if curl -sf --max-time 5 "http://gofr-neo4j:7474" >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}UNREACHABLE${NC}"
    echo "Neo4j not running at gofr-neo4j:7474. Start production infra first." >&2
    exit 1
fi

# Ensure output directory exists
mkdir -p tmp

# =============================================================================
# Run validation
# =============================================================================
echo -e "${BLUE}Running golden set validation...${NC}"
echo ""

uv run python simulation/scripts/validate_test_set.py \
    --require-nonempty \
    --report-json "$RESULTS_JSON" \
    --report-md "$RESULTS_MD"

VALIDATE_EXIT=$?

echo ""

if [ $VALIDATE_EXIT -ne 0 ]; then
    echo -e "${RED}Validation failed (exit code: $VALIDATE_EXIT)${NC}"
    exit $VALIDATE_EXIT
fi

# =============================================================================
# Post-validation action
# =============================================================================
case "$MODE" in
    save)
        echo -e "${BLUE}Saving as golden baseline...${NC}"
        uv run python simulation/scripts/golden_baseline.py save --from "$RESULTS_JSON"
        echo ""
        echo -e "${GREEN}Reports saved:${NC}"
        echo "  JSON: $RESULTS_JSON"
        echo "  Markdown: $RESULTS_MD"
        echo "  Golden: simulation/test_data/golden_baseline.json"
        ;;
    diff)
        echo -e "${BLUE}Comparing against saved baseline...${NC}"
        uv run python simulation/scripts/golden_baseline.py diff --current "$RESULTS_JSON"
        ;;
    validate)
        echo -e "${GREEN}Validation complete.${NC}"
        echo "  JSON: $RESULTS_JSON"
        echo "  Markdown: $RESULTS_MD"
        ;;
esac
