#!/bin/bash
# Build the gofr-iq base Docker image
# Usage: ./build-base.sh [--no-cache]
#
# This creates gofr-iq-base:latest by tagging gofr-base:latest
# Requires gofr-base:latest to be built first (from gofr-common)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SOURCE_IMAGE="gofr-base:latest"
TARGET_IMAGE="gofr-iq-base:latest"

echo "======================================================================="
echo "Building GOFR-IQ Base Image"
echo "======================================================================="
echo "Source: ${SOURCE_IMAGE}"
echo "Target: ${TARGET_IMAGE}"
echo "======================================================================="

# Check if source image exists
if ! docker image inspect "${SOURCE_IMAGE}" >/dev/null 2>&1; then
    echo "ERROR: Source image ${SOURCE_IMAGE} not found!"
    echo ""
    echo "Please build the base image first:"
    echo "  cd /home/parris3142/devroot/gofr-common"
    echo "  ./docker/build-base.sh"
    exit 1
fi

# Tag the base image for gofr-iq
docker tag "${SOURCE_IMAGE}" "${TARGET_IMAGE}"

echo ""
echo "======================================================================="
echo "Build complete: ${TARGET_IMAGE}"
echo "======================================================================="

# Verify the image
echo ""
echo "Verifying image..."
docker run --rm "${TARGET_IMAGE}" python --version
docker run --rm "${TARGET_IMAGE}" uv --version

echo ""
echo "Image size:"
docker images "gofr-iq-base" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

echo ""
echo "Next steps:"
echo "  ./docker/build-prod.sh  # Build production image"
