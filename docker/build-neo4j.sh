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

docker build \
    -f "${SCRIPT_DIR}/Dockerfile.neo4j" \
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
