#!/bin/bash
# Run GOFR-IQ development container
# Uses gofr-iq-dev:latest image (built from gofr-base:latest)
# Standard user: gofr (UID 1000, GID 1000)
#
# Usage:
#   ./scripts/run-dev.sh [OPTIONS]
#
# Options:
#   --mcp-port PORT      Override MCP port (default: from gofr_ports.env + 200)
#   --mcpo-port PORT     Override MCPO port (default: from gofr_ports.env + 200)
#   --web-port PORT      Override Web port (default: from gofr_ports.env + 200)
#   --network NAME       Docker network (default: gofr-net)
#   -h, --help           Show this help
#
# REQUIREMENTS:
#   - Docker must be installed and running
#   - gofr_ports.env must exist (run scripts/generate_envs.sh if missing)
#   - gofr-iq-dev:latest image must be built (run docker/build-dev.sh)
#
# This container provides an isolated development environment with:
#   - Access to host Docker socket (for managing prod containers)
#   - Project mounted at /home/gofr/devroot/gofr-iq
#   - Persistent data volume for state
#   - Ports exposed for MCP/MCPO/Web servers
#
# See docs/development.md for full development setup guide.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# gofr-common is now a git submodule at lib/gofr-common, no separate mount needed

# Standard GOFR user - all projects use same user
GOFR_USER="gofr"
GOFR_UID=1000
GOFR_GID=1000

# Container and image names
CONTAINER_NAME="gofr-iq-dev"
IMAGE_NAME="gofr-iq-dev:latest"

# Load port configuration from .env file
set -a  # automatically export all variables
source "$PROJECT_ROOT/lib/gofr-common/config/gofr_ports.env"
set +a
# Add 200 to dev ports to separate from prod (8080 -> 8280, 8081 -> 8281, 8082 -> 8282)
MCP_PORT=$((GOFR_IQ_MCP_PORT + 200))
MCPO_PORT=$((GOFR_IQ_MCPO_PORT + 200))
WEB_PORT=$((GOFR_IQ_WEB_PORT + 200))
DOCKER_NETWORK="${GOFR_IQ_DOCKER_NETWORK:-gofr-net}"

# Parse command line arguments
while [ $# -gt 0 ]; do
    case $1 in
        --mcp-port)
            MCP_PORT="$2"
            shift 2
            ;;
        --mcpo-port)
            MCPO_PORT="$2"
            shift 2
            ;;
        --web-port)
            WEB_PORT="$2"
            shift 2
            ;;
        --network)
            DOCKER_NETWORK="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--mcp-port PORT] [--mcpo-port PORT] [--web-port PORT] [--network NAME]"
            exit 1
            ;;
    esac
done

echo "======================================================================="
echo "Starting GOFR-IQ Development Container"
echo "======================================================================="
echo "User: ${GOFR_USER} (UID=${GOFR_UID}, GID=${GOFR_GID})"
echo "Ports: MCP=$MCP_PORT, MCPO=$MCPO_PORT, Web=$WEB_PORT"
echo "Network: $DOCKER_NETWORK"
echo "======================================================================="

# Create docker network if it doesn't exist
if ! docker network inspect $DOCKER_NETWORK >/dev/null 2>&1; then
    echo "Creating network: $DOCKER_NETWORK"
    docker network create $DOCKER_NETWORK
fi

# Create docker volume for persistent data
VOLUME_NAME="gofr-iq-data-dev"
if ! docker volume inspect $VOLUME_NAME >/dev/null 2>&1; then
    echo "Creating volume: $VOLUME_NAME"
    docker volume create $VOLUME_NAME
fi

# Stop and remove existing container
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping existing container: $CONTAINER_NAME"
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi

# Get docker socket group ID for proper permissions
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo "999")

# Run container with Docker socket mounted for Docker-in-Docker
docker run -d \
    --name "$CONTAINER_NAME" \
    --network "$DOCKER_NETWORK" \
    -p ${MCP_PORT}:${MCP_PORT} \
    -p ${MCPO_PORT}:${MCPO_PORT} \
    -p ${WEB_PORT}:${WEB_PORT} \
    -v "$PROJECT_ROOT:/home/gofr/devroot/gofr-iq:rw" \
    -v ${VOLUME_NAME}:/home/gofr/devroot/gofr-iq/data:rw \
    -v /var/run/docker.sock:/var/run/docker.sock:rw \
    -v /home/parris3142/devroot/gofr-plot:/home/gofr/devroot/gofr-plot:ro \
    -v /home/parris3142/devroot/gofr-doc:/home/gofr/devroot/gofr-doc:ro \
    --group-add ${DOCKER_GID} \
    -e GOFR_IQ_ENV=development \
    -e GOFR_IQ_DEBUG=true \
    -e GOFR_IQ_LOG_LEVEL=DEBUG \
    "$IMAGE_NAME"

echo ""
echo "======================================================================="
echo "Container started: $CONTAINER_NAME"
echo "======================================================================="
echo ""
echo "To enter container:"
echo "  docker exec -it $CONTAINER_NAME bash"
echo ""
echo "To activate virtual environment:"
echo "  source .venv/bin/activate"
echo ""
