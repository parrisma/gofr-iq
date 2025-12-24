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

# Get build metadata
BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

echo "Building gofr-iq production image version: $VERSION"
echo "Build date: $BUILD_DATE"
echo "Git commit: $GIT_COMMIT"

# Build the image with version tag and latest
docker build \
    -f docker/Dockerfile.prod \
    --build-arg BUILD_DATE="$BUILD_DATE" \
    --build-arg GIT_COMMIT="$GIT_COMMIT" \
    --build-arg VERSION="$VERSION" \
    -t gofr-iq-prod:${VERSION} \
    -t gofr-iq-prod:latest \
    .

echo ""
echo "Successfully built:"
echo "  - gofr-iq-prod:${VERSION}"
echo "  - gofr-iq-prod:latest"
echo ""
docker images | grep gofr-iq-prod | head -5
