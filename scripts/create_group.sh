#!/bin/bash
# Wrapper script for create_group.py (gofr-iq)
# Calls the shared create_group.py from gofr-common with GOFR_IQ prefix
#
# Usage:
#   ./create_group.sh <group-name> [options]
#   ./create_group.sh --list
#
# Examples:
#   ./create_group.sh reuters-feed
#   ./create_group.sh sales-team --expires 604800
#   ./create_group.sh --list

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source environment configuration
if [ -f "$SCRIPT_DIR/gofriq.env" ]; then
    source "$SCRIPT_DIR/gofriq.env"
fi

# Find the shared script
COMMON_SCRIPT="$PROJECT_ROOT/lib/gofr-common/scripts/create_group.py"

if [ ! -f "$COMMON_SCRIPT" ]; then
    echo "ERROR: Shared script not found at $COMMON_SCRIPT" >&2
    echo "Make sure gofr-common is properly installed in lib/" >&2
    exit 1
fi

# Ensure JWT secret is set
if [ -z "$GOFR_IQ_JWT_SECRET" ]; then
    echo "ERROR: GOFR_IQ_JWT_SECRET environment variable not set" >&2
    echo "" >&2
    echo "Please set it in scripts/gofriq.env or your environment:" >&2
    echo "  export GOFR_IQ_JWT_SECRET='your-secret-key'" >&2
    exit 1
fi

# Run the shared script with GOFR_IQ prefix
cd "$PROJECT_ROOT"

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

exec python "$COMMON_SCRIPT" --prefix GOFR_IQ "$@"
