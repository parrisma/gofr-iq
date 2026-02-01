#!/bin/bash
# =============================================================================
# GOFR-IQ Client Management Script (Wrapper)
# =============================================================================
# Usage (order matters):
#   ./scripts/manage_client.sh [global options] <command> [command options]
#
# Examples:
#   ./scripts/manage_client.sh --token "$TOKEN" list
#   ./scripts/manage_client.sh --token "$TOKEN" create --name "Test" --type HEDGE_FUND
#   ./scripts/manage_client.sh --docker --token "$TOKEN" list
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"
uv run "$PROJECT_DIR/scripts/manage_client.py" "$@"
