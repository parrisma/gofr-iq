#!/bin/bash
# Start ChromaDB server for GOFR-IQ
#
# Usage: ./start-chromadb.sh [-e] [-r] [-p PORT] [-n NETWORK]
# Options:
#   -e           Ephemeral mode (no volume, data lost on stop)
#   -r           Recreate volume (drop and recreate if it exists)
#   -p PORT      Port to expose ChromaDB on (default: 8100 or GOFR_IQ_CHROMADB_PORT)
#   -n NETWORK   Docker network to attach to (default: gofr-net or GOFR_DOCKER_NETWORK)
#
# Environment Variables:
#   GOFR_IQ_CHROMADB_PORT  - Default port for ChromaDB (default: 8100)
#   GOFR_DOCKER_NETWORK    - Default Docker network (default: gofr-net)
#
# Examples:
#   ./start-chromadb.sh                    # Persistent on port 8100, gofr-net
#   ./start-chromadb.sh -e                 # Ephemeral for testing
#   ./start-chromadb.sh -p 8200            # Custom port
#   ./start-chromadb.sh -r                 # Recreate volume (fresh start)
#   ./start-chromadb.sh -e -p 8100         # Ephemeral on port 8100

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults
EPHEMERAL=false
RECREATE_VOLUME=false
CHROMADB_PORT="${GOFR_IQ_CHROMADB_PORT:-8100}"
NETWORK="${GOFR_DOCKER_NETWORK:-gofr-net}"

CONTAINER_NAME="gofr-iq-chromadb"
IMAGE_NAME="gofr-iq-chromadb:latest"
VOLUME_NAME="gofr-iq-chromadb-data"

# Parse command line arguments
while getopts "erp:n:" opt; do
    case $opt in
        e)
            EPHEMERAL=true
            ;;
        r)
            RECREATE_VOLUME=true
            ;;
        p)
            CHROMADB_PORT=$OPTARG
            ;;
        n)
            NETWORK=$OPTARG
            ;;
        \?)
            echo "Usage: $0 [-e] [-r] [-p PORT] [-n NETWORK]"
            echo "  -e           Ephemeral mode (no persistence)"
            echo "  -r           Recreate volume (fresh start)"
            echo "  -p PORT      Port to expose (default: 8100)"
            echo "  -n NETWORK   Docker network to attach to"
            exit 1
            ;;
    esac
done

echo "======================================================================="
echo "Starting ChromaDB Server"
echo "======================================================================="
echo "Port:       $CHROMADB_PORT"
echo "Container:  $CONTAINER_NAME"
echo "Mode:       $([ "$EPHEMERAL" = true ] && echo "Ephemeral" || echo "Persistent")"
[ -n "$NETWORK" ] && echo "Network:    $NETWORK"
echo ""

# Build image if it doesn't exist
if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${IMAGE_NAME}$"; then
    echo "Image not found, building..."
    "${SCRIPT_DIR}/build-chromadb.sh"
    echo ""
fi

# Stop and remove existing container if it exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping existing container..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi

# Handle volume for persistent mode
VOLUME_ARGS=""
if [ "$EPHEMERAL" = false ]; then
    # Handle volume creation/recreation
    if [ "$RECREATE_VOLUME" = true ]; then
        echo "Recreate flag (-r) detected"
        if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
            echo "Removing existing volume..."
            docker volume rm "$VOLUME_NAME" 2>/dev/null || {
                echo "ERROR: Failed to remove volume. It may be in use."
                exit 1
            }
        fi
    fi

    # Create volume if it doesn't exist
    if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
        echo "Creating volume $VOLUME_NAME..."
        docker volume create "$VOLUME_NAME"
    else
        echo "Using existing volume $VOLUME_NAME"
    fi

    VOLUME_ARGS="-v ${VOLUME_NAME}:/chroma/chroma"
fi

# Network args
NETWORK_ARGS=""
if [ -n "$NETWORK" ]; then
    # Create network if it doesn't exist
    if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
        echo "Creating network $NETWORK..."
        docker network create "$NETWORK"
    fi
    NETWORK_ARGS="--network $NETWORK"
fi

# Start container
echo "Starting ChromaDB container..."
docker run -d \
    --name "$CONTAINER_NAME" \
    $NETWORK_ARGS \
    -p "${CHROMADB_PORT}:8000" \
    $VOLUME_ARGS \
    "$IMAGE_NAME"

# Wait for server to be ready
echo "Waiting for ChromaDB to be ready..."
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -sf "http://localhost:${CHROMADB_PORT}/api/v1/heartbeat" > /dev/null 2>&1; then
        echo ""
        echo "======================================================================="
        echo "🔮 ChromaDB Vector Database"
        echo ""
        echo "Server:     http://localhost:${CHROMADB_PORT}"
        echo "Heartbeat:  http://localhost:${CHROMADB_PORT}/api/v1/heartbeat"
        echo "API Docs:   http://localhost:${CHROMADB_PORT}/docs"
        echo ""
        echo "Storage:    $([ "$EPHEMERAL" = true ] && echo "Ephemeral (in-memory)" || echo "Volume: $VOLUME_NAME")"
        echo ""
        echo "Management:"
        echo "  View logs:  docker logs -f $CONTAINER_NAME"
        echo "  Stop:       ./stop-chromadb.sh"
        echo "  Restart:    ./stop-chromadb.sh && ./start-chromadb.sh"
        echo "======================================================================="
        exit 0
    fi
    ATTEMPT=$((ATTEMPT + 1))
    printf "."
    sleep 1
done

echo ""
echo "ERROR: ChromaDB failed to start within ${MAX_ATTEMPTS} seconds"
docker logs "$CONTAINER_NAME"
exit 1
