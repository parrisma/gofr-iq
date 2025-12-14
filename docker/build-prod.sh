#!/bin/bash
# Build gofr-iq production image with auto-versioning
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Extract version from pyproject.toml
VERSION=$(grep -m1 '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')

if [ -z "$VERSION" ]; then
    echo "ERROR: Could not extract version from pyproject.toml"
    exit 1
fi

echo "Building gofr-iq production image version: $VERSION"

# Build the image with version tag and latest
docker build \
    -f docker/Dockerfile.prod \
    -t gofr-iq-prod:${VERSION} \
    -t gofr-iq-prod:latest \
    .

echo ""
echo "Successfully built:"
echo "  - gofr-iq-prod:${VERSION}"
echo "  - gofr-iq-prod:latest"
echo ""
docker images | grep gofr-iq-prod | head -5
