#!/bin/bash
# Build Vault Docker image for GOFR-IQ

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_NAME="gofr-iq-vault"
IMAGE_TAG="latest"

echo "======================================================================="
echo "Building Vault Docker image"
echo "======================================================================="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

# Get build metadata
BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

docker build \
    -f "${SCRIPT_DIR}/Dockerfile.vault" \
    --build-arg BUILD_DATE="$BUILD_DATE" \
    --build-arg GIT_COMMIT="$GIT_COMMIT" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    "${SCRIPT_DIR}"

echo ""
echo "======================================================================="
echo "Build complete: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "======================================================================="
echo ""
echo "To run Vault:"
echo "  ../lib/gofr-common/scripts/manage_vault.sh start   # Start Vault"
echo "  ../lib/gofr-common/scripts/manage_vault.sh stop    # Stop Vault"
echo "  ../lib/gofr-common/scripts/manage_vault.sh status  # Check status"
