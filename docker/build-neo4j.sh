#!/bin/bash
# Build Neo4j Docker image for GOFR-IQ

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_NAME="gofr-iq-neo4j"
IMAGE_TAG="latest"

echo "======================================================================="
echo "Building Neo4j Docker image"
echo "======================================================================="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

# Get build metadata
BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

docker build \
    -f "${SCRIPT_DIR}/Dockerfile.neo4j" \
    --build-arg BUILD_DATE="$BUILD_DATE" \
    --build-arg GIT_COMMIT="$GIT_COMMIT" \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    "${SCRIPT_DIR}"

echo ""
echo "======================================================================="
echo "Build complete: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "======================================================================="
echo ""
echo "To run Neo4j:"
echo "  ./start-neo4j.sh           # Persistent storage"
echo "  ./start-neo4j.sh -e        # Ephemeral (no persistence)"
echo "  ./start-neo4j.sh -p 7687   # Custom Bolt port"
