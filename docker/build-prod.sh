#!/bin/bash
# Build GOFR-IQ Production Image

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

docker build \
-f docker/Dockerfile.prod \
-t gofr-iq_prod:latest \
.
