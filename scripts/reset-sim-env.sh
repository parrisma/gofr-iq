#!/bin/bash
# =============================================================================
# Reset Simulation Environment
# =============================================================================
# Tears down ALL data and rebuilds from zero to injection-ready state.
# Run this whenever you make big changes and need a clean baseline.
#
# What it does:
#   1. start-prod.sh --reset  (wipe data, Vault secrets, graph bootstrap)
#   2. run_simulation.sh --count 0  (groups, tokens, sources, universe, clients+holdings)
#   3. Verify graph state (clients, instruments, holdings, groups)
#
# After this script succeeds you can:
#   - Inject golden test set:  uv run simulation/scripts/inject_test_data.py simulation/test_data/avatar_test_set.json
#   - Inject custom docs:      uv run simulation/scripts/inject_test_data.py /path/to/docs.json
#   - Run random simulation:   ./simulation/run_simulation.sh --count 50
#   - Validate avatar feeds:   uv run simulation/scripts/validate_test_set.py
#
# Usage:
#   ./scripts/reset-sim-env.sh                           # Uses key from Vault
#   ./scripts/reset-sim-env.sh --openrouter-key KEY      # Provide key explicitly
#   ./scripts/reset-sim-env.sh --skip-reset              # Skip prod reset (reuse running stack)
#   ./scripts/reset-sim-env.sh --inject-golden           # Also inject golden test set
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SECRETS_DIR="${PROJECT_ROOT}/secrets"

# Defaults
OPENROUTER_KEY=""
SKIP_RESET=false
INJECT_GOLDEN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --openrouter-key)
            OPENROUTER_KEY="$2"
            shift 2
            ;;
        --skip-reset)
            SKIP_RESET=true
            shift
            ;;
        --inject-golden)
            INJECT_GOLDEN=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Tears down ALL data and rebuilds to injection-ready state."
            echo ""
            echo "Options:"
            echo "  --openrouter-key KEY   OpenRouter API key (default: read from Vault)"
            echo "  --skip-reset           Skip prod reset, reuse running stack"
            echo "  --inject-golden        Also inject the golden test set after setup"
            echo "  -h, --help             Show this help"
            echo ""
            echo "After success, inject docs with:"
            echo "  uv run simulation/scripts/inject_test_data.py simulation/test_data/avatar_test_set.json"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

cd "$PROJECT_ROOT"

echo ""
echo "======================================================================="
echo "  RESET SIMULATION ENVIRONMENT"
echo "======================================================================="
echo "  Skip reset:     ${SKIP_RESET}"
echo "  Inject golden:  ${INJECT_GOLDEN}"
echo "======================================================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Full production reset
# ---------------------------------------------------------------------------
if [ "$SKIP_RESET" = false ]; then
    echo "=== Step 1/3: Production reset ==="

    # Get OpenRouter key: flag > Vault > prompt
    if [ -z "$OPENROUTER_KEY" ] && [ -f "${SECRETS_DIR}/vault_root_token" ]; then
        VAULT_TOKEN=$(cat "${SECRETS_DIR}/vault_root_token")
        if [ -f /.dockerenv ]; then
            VAULT_ADDR="http://gofr-vault:8201"
        else
            VAULT_ADDR="http://localhost:8201"
        fi
        OPENROUTER_KEY=$(docker exec \
            -e VAULT_ADDR="$VAULT_ADDR" \
            -e VAULT_TOKEN="$VAULT_TOKEN" \
            gofr-vault vault kv get -field=value \
            secret/gofr/config/api-keys/openrouter 2>/dev/null || true)
    fi

    if [ -z "$OPENROUTER_KEY" ]; then
        echo "ERROR: No OpenRouter key found. Provide via --openrouter-key or store in Vault first." >&2
        exit 1
    fi

    # Auto-confirm the reset prompt in start-prod.sh
    echo "yes" | ./scripts/start-prod.sh --reset --openrouter-key "$OPENROUTER_KEY"

    echo ""
    echo "  Waiting 10s for services to stabilize..."
    sleep 10
    echo "  [OK] Production stack reset and running"
    echo ""
else
    echo "=== Step 1/3: Skipped (--skip-reset) ==="
    echo ""
fi

# ---------------------------------------------------------------------------
# Step 2: Initialize universe, clients, holdings, watchlists
# ---------------------------------------------------------------------------
echo "=== Step 2/3: Initialize simulation universe ==="
./simulation/run_simulation.sh --count 0 --verbose
echo ""
echo "  [OK] Universe, clients, holdings, and watchlists loaded"
echo ""

# ---------------------------------------------------------------------------
# Step 3: Verify graph state
# ---------------------------------------------------------------------------
echo "=== Step 3/3: Verify graph state ==="

source docker/.env

VERIFY_RESULT=$(docker exec -e NEO4J_PASSWORD="$NEO4J_PASSWORD" gofr-iq-mcp python3 -c "
import os, sys
from neo4j import GraphDatabase
driver = GraphDatabase.driver('bolt://gofr-neo4j:7687', auth=('neo4j', os.environ['NEO4J_PASSWORD']))
errors = []
with driver.session() as s:
    # Clients exist
    r = s.run('MATCH (c:Client) RETURN count(c) AS n').single()
    n = r['n']
    if n == 0:
        errors.append('NO CLIENTS in graph')
    else:
        print(f'  Clients:      {n}')

    # Instruments exist
    r = s.run('MATCH (i:Instrument) RETURN count(i) AS n').single()
    n = r['n']
    if n == 0:
        errors.append('NO INSTRUMENTS in graph')
    else:
        print(f'  Instruments:  {n}')

    # Holdings edges exist
    r = s.run('MATCH ()-[:HOLDS]->() RETURN count(*) AS n').single()
    n = r['n']
    if n == 0:
        errors.append('NO HOLDS edges - client portfolios are empty')
    else:
        print(f'  Holdings:     {n}')

    # Watchlist edges exist
    r = s.run('MATCH ()-[:WATCHES]->() RETURN count(*) AS n').single()
    n = r['n']
    if n == 0:
        errors.append('NO WATCHES edges - client watchlists are empty')
    else:
        print(f'  Watchlists:   {n}')

    # Groups exist
    r = s.run('MATCH (g:Group) RETURN count(g) AS n').single()
    n = r['n']
    print(f'  Groups:       {n}')

    # Client profiles
    r = s.run('MATCH (c:Client)-[:HAS_PROFILE]->(p:ClientProfile) RETURN count(p) AS n').single()
    print(f'  Profiles:     {r[\"n\"]}')

    # Documents (should be zero after reset)
    r = s.run('MATCH (d:Document) RETURN count(d) AS n').single()
    print(f'  Documents:    {r[\"n\"]} (expected 0 before injection)')

driver.close()

if errors:
    print()
    for e in errors:
        print(f'  FAIL: {e}')
    sys.exit(1)
" 2>&1)

VERIFY_EXIT=$?
echo "$VERIFY_RESULT"

if [ $VERIFY_EXIT -ne 0 ]; then
    echo ""
    echo "  FAILED: Graph state verification failed"
    echo "  Check output above for details"
    exit 1
fi

echo ""
echo "  [OK] Graph state verified"
echo ""

# ---------------------------------------------------------------------------
# Optional: Inject golden test set
# ---------------------------------------------------------------------------
if [ "$INJECT_GOLDEN" = true ]; then
    echo "=== Bonus: Injecting golden test set ==="
    source docker/.env
    uv run simulation/scripts/inject_test_data.py simulation/test_data/avatar_test_set.json
    echo ""
    echo "  [OK] Golden test set injected"
    echo ""
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo "======================================================================="
echo "  SIMULATION ENVIRONMENT READY"
echo "======================================================================="
echo ""
echo "  Next steps:"
echo "    # Inject golden test set"
echo "    uv run simulation/scripts/inject_test_data.py simulation/test_data/avatar_test_set.json"
echo ""
echo "    # Validate avatar feeds"
echo "    uv run simulation/scripts/validate_test_set.py"
echo ""
echo "    # Or inject custom docs"
echo "    uv run simulation/scripts/inject_test_data.py /path/to/your/docs.json"
echo ""
echo "    # Or run full UAT (inject + validate)"
echo "    ./simulation/run_avatar_simulation.sh --test-set --skip-reset"
echo ""
