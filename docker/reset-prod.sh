#!/bin/bash
# =============================================================================
# Production Reset Script ("Nuke & Pave")
# =============================================================================
# DANGER: This script destroys ALL data in:
# - Docker volumes (via down -v)
# - Persistent data directories (data/storage, data/auth, data/vault)
#
# Use this only when you want to reset the environment to a completely clean
# state, essentially simulating a fresh install.
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data"

# Confirm with user
read -p "DANGER: This will delete ALL persistent data. Are you sure? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo "1. Stopping all containers and removing volumes..."
cd "${PROJECT_ROOT}/docker"
docker compose down -v || true

echo "2. Removing persistent data directories..."
# Check if directories exist before trying to remove
if [ -d "${DATA_DIR}" ]; then
    # We use sudo if needed, but in dev container user owns these usually.
    # Try current user first.
    rm -rf "${DATA_DIR}/storage"/* 2>/dev/null || true
    rm -rf "${DATA_DIR}/auth"/* 2>/dev/null || true
    rm -rf "${DATA_DIR}/vault"/* 2>/dev/null || true
    rm -rf "${DATA_DIR}/chroma"/* 2>/dev/null || true
    rm -rf "${DATA_DIR}/neo4j"/* 2>/dev/null || true
    echo "   - Cleared data/*"
else
    echo "   - Data directory not found, skipping."
fi

echo "3. Removing Vault credentials..."
rm -rf "${PROJECT_ROOT}/secrets"
echo "   - Removed secrets/"

echo "4. Removing generated configs..."
rm -rf "${PROJECT_ROOT}/config/generated"
rm -f "${PROJECT_ROOT}/docker/.env"
echo "   - Removed config/generated and docker/.env"

echo "================================================================="
echo "Reset Complete. The environment is clean."
echo "To restart from scratch:"
echo "  1. docker compose up -d gofr-vault"
echo "  2. uv run scripts/bootstrap.py --auto-init"
echo "  3. ./docker/start-prod.sh --fresh"
echo "  5. docker compose up -d"
echo "================================================================="
