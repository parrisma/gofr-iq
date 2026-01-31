#!/bin/bash
# =============================================================================
# Simulation Runner - Uses Production Environment
# =============================================================================
# Thin wrapper to run the simulation using the production stack configuration.
# Environment/secret loading and health checks are handled inside run_simulation.py.
#
# Common usage:
#   ./run_simulation.sh --count 50                    # Generate and ingest 50 new documents
#   ./run_simulation.sh --ingest-only                 # Ingest existing documents from test_output
#   ./run_simulation.sh --skip-generate               # Same as --ingest-only
#   ./run_simulation.sh --validate-only               # Setup/validation without data generation
#   ./run_simulation.sh --init-groups-only            # Create groups then exit
#   ./run_simulation.sh --init-tokens-only            # Create groups and tokens then exit
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

exec uv run python "$PROJECT_ROOT/simulation/run_simulation.py" "$@"
