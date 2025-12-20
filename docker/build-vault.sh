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

docker build \
    -f "${SCRIPT_DIR}/Dockerfile.vault" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    "${SCRIPT_DIR}"

echo ""
echo "======================================================================="
echo "Build complete: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "======================================================================="
echo ""
echo "To run Vault:"
echo "  ./run-vault.sh           # Persistent storage"
echo "  ./run-vault.sh -e        # Ephemeral (no persistence)"
echo "  ./run-vault.sh -p 8201   # Custom port"
