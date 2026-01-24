#!/bin/bash
# =============================================================================
# Simulation Runner - Uses Production Environment
# =============================================================================
# Thin wrapper to run the simulation using the production stack configuration.
# Environment/secret loading and health checks are handled inside run_simulation.py.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

exec uv run python "$PROJECT_ROOT/simulation/run_simulation.py" "$@"
