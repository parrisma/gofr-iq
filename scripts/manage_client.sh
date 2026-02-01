#!/bin/bash
# =============================================================================
# GOFR-IQ Client Management Script (Wrapper)
# =============================================================================
# Usage:
#   ./scripts/manage_client.sh <command> [options]
#
# Examples:
#   ./scripts/manage_client.sh list --token "$TOKEN"
#   ./scripts/manage_client.sh create --name "Test" --type HEDGE_FUND --token "$TOKEN"
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"
uv run "$PROJECT_DIR/scripts/manage_client.py" "$@"
