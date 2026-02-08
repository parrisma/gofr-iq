#!/bin/bash
# =============================================================================
# Avatar Feed UAT Simulation
# =============================================================================
# End-to-end UAT: reset prod → bootstrap clients/sources/docs → validate feeds.
#
# Usage:
#   ./simulation/run_avatar_simulation.sh                     # Full run (200 docs)
#   ./simulation/run_avatar_simulation.sh --count 50          # Fewer docs (faster)
#   ./simulation/run_avatar_simulation.sh --model MODEL       # Use specific LLM model
#   ./simulation/run_avatar_simulation.sh --skip-reset        # Skip prod reset
#   ./simulation/run_avatar_simulation.sh --skip-ingest       # Skip doc generation/ingest
#   ./simulation/run_avatar_simulation.sh --validate-only     # Only run validation
#   ./simulation/run_avatar_simulation.sh --verbose           # Verbose output
#   ./simulation/run_avatar_simulation.sh --test-set          # Inject Golden Set test data (Clean Start)
#
# Pipeline:
#   1. ./scripts/start-prod.sh --reset    (tear down all data)
#   2. ./simulation/run_simulation.sh     (create groups, sources, clients, generate+ingest docs)
#   3. uv run simulation/validate_avatar_feeds.py  (query feeds via MCP, assert invariants)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Defaults
DOC_COUNT=200
SKIP_RESET=false
SKIP_INGEST=false
VALIDATE_ONLY=false
VERBOSE=""
MODEL_NAME=""
USE_TEST_SET=false
OPENROUTER_KEY=""
EXPECTATIONS_FILE=""
REPORT_JSON=""
REPORT_MD=""
REQUIRE_NONEMPTY=false
MIN_PASS_RATE=""
FORCE_NO_RESET=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --count)
            DOC_COUNT="$2"
            shift 2
            ;;
        --model)
            MODEL_NAME="$2"
            shift 2
            ;;
        --openrouter-key)
            OPENROUTER_KEY="$2"
            shift 2
            ;;
        --skip-reset)
            SKIP_RESET=true
            shift
            ;;
        --skip-ingest)
            SKIP_INGEST=true
            shift
            ;;
        --validate-only)
            VALIDATE_ONLY=true
            SKIP_RESET=true
            SKIP_INGEST=true
            shift
            ;;
        --test-set)
            USE_TEST_SET=true
            shift
            ;;
        --expectations)
            EXPECTATIONS_FILE="$2"
            shift 2
            ;;
        --report-json)
            REPORT_JSON="$2"
            shift 2
            ;;
        --report-md)
            REPORT_MD="$2"
            shift 2
            ;;
        --require-nonempty)
            REQUIRE_NONEMPTY=true
            shift
            ;;
        --min-pass-rate)
            MIN_PASS_RATE="$2"
            shift 2
            ;;
        --force)
            FORCE_NO_RESET=true
            shift
            ;;
        --verbose|-v)
            VERBOSE="--verbose"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --count N              Number of documents to generate (default: 200)"
            echo "  --model MODEL          LLM model for document generation"
            echo "  --openrouter-key KEY   OpenRouter API key"
            echo "  --skip-reset           Skip production stack reset"
            echo "  --skip-ingest          Skip document ingestion"
            echo "  --validate-only        Only run validation (implies --skip-reset --skip-ingest)"
            echo "  --test-set             Use golden test set (deterministic)"
            echo "  --expectations PATH    JSON file with expected results"
            echo "  --report-json PATH     Output results as JSON"
            echo "  --report-md PATH       Output results as Markdown"
            echo "  --require-nonempty     Fail if any client feed is empty"
            echo "  --min-pass-rate N      Minimum pass rate (0.0-1.0)"
            echo "  --force                Allow --skip-reset without warning (advanced)"
            echo "  --verbose, -v          Verbose output"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

cd "$PROJECT_ROOT"

# Build model arg for passthrough
MODEL_ARG=""
if [ -n "$MODEL_NAME" ]; then
    MODEL_ARG="--model $MODEL_NAME"
fi

echo ""
echo "======================================================================="
echo "🎯  AVATAR FEED UAT SIMULATION"
echo "======================================================================="
if [ "$USE_TEST_SET" = true ]; then
    echo "  MODE:          GOLDEN TEST SET (Deterministic)"
else
    echo "  MODE:          RANDOM SIMULATION"
    echo "  Documents:     ${DOC_COUNT}"
fi
echo "  Skip reset:    ${SKIP_RESET}"
echo "  Skip ingest:   ${SKIP_INGEST}"
echo "======================================================================="
echo ""

# ─── Guard: Warn if skipping reset without --force ───
if [ "$SKIP_RESET" = true ] && [ "$FORCE_NO_RESET" = false ] && [ "$USE_TEST_SET" = true ]; then
    echo "WARNING: Running test-set validation without reset may give non-deterministic results."
    echo "The golden test set expects a clean database state."
    echo ""
    echo "Options:"
    echo "  1. Remove --skip-reset to run a full reset first"
    echo "  2. Add --force to suppress this warning (if you know the state is clean)"
    echo ""
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# ─── Step 1: Reset prod (tears down ALL data) ───
if [ "$SKIP_RESET" = false ]; then
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Step 1/3: Resetting production stack"
    echo "═══════════════════════════════════════════════════════════════"
    # Build openrouter key arg if provided
    OPENROUTER_ARG=""
    if [ -n "$OPENROUTER_KEY" ]; then
        OPENROUTER_ARG="--openrouter-key $OPENROUTER_KEY"
    fi
    # Use yes to auto-confirm the reset prompt
    echo "yes" | ./scripts/start-prod.sh --reset $OPENROUTER_ARG
    echo ""
    echo "  ✅ Production stack reset and running"
    echo ""
    
    # Wait for services to stabilize after reset
    echo "  ⏳ Waiting 10s for services to stabilize..."
    sleep 10
else
    echo "  ⏭  Skipping reset (--skip-reset)"
fi

# ─── Step 2: Ingest Data (Random or Test Set) ───
if [ "$SKIP_INGEST" = false ]; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    if [ "$USE_TEST_SET" = true ]; then
        echo "  Step 2/3: Injecting GOLDEN TEST SET (Deterministic)"
        echo "═══════════════════════════════════════════════════════════════"
        
        # 1. Init Universe (Clients/Groups) ONLY - no documents
        echo "  Initializing Universe (Clients, Groups)..."
        ./simulation/run_simulation.sh --count 0 --verbose
        
        # 2. Inject Test Data
        echo "  Injecting deterministic documents..."
        uv run simulation/scripts/inject_test_data.py simulation/test_data/avatar_test_set.json
        
    else
        echo "  Step 2/3: Running simulation (${DOC_COUNT} documents)"
        echo "═══════════════════════════════════════════════════════════════"
        
        # Clear cached stories to force regeneration with fresh data
        rm -rf simulation/test_output/synthetic_*.json 2>/dev/null || true
        
        ./simulation/run_simulation.sh --count "$DOC_COUNT" --regenerate $MODEL_ARG $VERBOSE
    fi
    
    echo ""
    echo "  ✅ Data Setup complete"
    echo ""
else
    echo "  ⏭  Skipping ingestion (--skip-ingest)"
fi

# ─── Step 3: Validate avatar feeds ───
echo ""
echo "==============================================================================="
echo "  Step 3/3: Validating avatar feeds via MCP"
echo "==============================================================================="

# Build validator arguments
VALIDATOR_ARGS=""
if [ -n "$EXPECTATIONS_FILE" ]; then
    VALIDATOR_ARGS="$VALIDATOR_ARGS --expectations $EXPECTATIONS_FILE"
fi
if [ -n "$REPORT_JSON" ]; then
    VALIDATOR_ARGS="$VALIDATOR_ARGS --report-json $REPORT_JSON"
fi
if [ -n "$REPORT_MD" ]; then
    VALIDATOR_ARGS="$VALIDATOR_ARGS --report-md $REPORT_MD"
fi
if [ "$REQUIRE_NONEMPTY" = true ]; then
    VALIDATOR_ARGS="$VALIDATOR_ARGS --require-nonempty"
fi
if [ -n "$MIN_PASS_RATE" ]; then
    VALIDATOR_ARGS="$VALIDATOR_ARGS --min-pass-rate $MIN_PASS_RATE"
fi

if [ "$USE_TEST_SET" = true ]; then
    # Use the specialized Golden Set validator which checks specific Test Matrix assertions
    uv run python "$PROJECT_ROOT/simulation/scripts/validate_test_set.py" $VALIDATOR_ARGS
else
    # Use the generic validator for random simulations
    uv run python "$PROJECT_ROOT/simulation/validate_avatar_feeds.py" $VERBOSE $VALIDATOR_ARGS
fi

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "🎉  AVATAR FEED UAT: ALL TESTS PASSED"
else
    echo "💥  AVATAR FEED UAT: SOME TESTS FAILED (exit code: $EXIT_CODE)"
fi
echo ""

exit $EXIT_CODE
