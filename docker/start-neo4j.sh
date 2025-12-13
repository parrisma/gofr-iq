#!/bin/bash
# Start Neo4j server for GOFR-IQ with automatic rolling backups
#
# Usage: ./start-neo4j.sh [-e] [-r] [-p BOLT_PORT] [-w HTTP_PORT] [-n NETWORK] [-b]
# Options:
#   -e              Ephemeral mode (no volume, data lost on stop)
#   -r              Recreate volume (drop and recreate if it exists)
#   -p BOLT_PORT    Bolt port (default: 7687 or GOFR_IQ_NEO4J_BOLT_PORT)
#   -w HTTP_PORT    HTTP port (default: 7474 or GOFR_IQ_NEO4J_HTTP_PORT)
#   -n NETWORK      Docker network to attach to (default: gofr-net)
#   -b              Disable automatic backups on startup
#
# Environment Variables:
#   GOFR_IQ_NEO4J_BOLT_PORT  - Default Bolt port (default: 7687)
#   GOFR_IQ_NEO4J_HTTP_PORT  - Default HTTP port (default: 7474)
#   GOFR_IQ_NEO4J_PASSWORD   - Neo4j password (default: testpassword)
#   GOFR_DOCKER_NETWORK      - Default Docker network (default: gofr-net)
#   GOFR_BACKUP_ENABLED      - Enable/disable backups (default: true)
#   GOFR_BACKUP_RETENTION    - Days to keep backups (default: 7)
#   GOFR_BACKUP_MAX_COUNT    - Max backups to keep (default: 10)
#
# Examples:
#   ./start-neo4j.sh                    # Persistent on default ports, gofr-net, with backups
#   ./start-neo4j.sh -e                 # Ephemeral for testing (no backups)
#   ./start-neo4j.sh -p 7688 -w 7475    # Custom ports
#   ./start-neo4j.sh -r                 # Recreate volume (fresh database)
#   ./start-neo4j.sh -b                 # Disable backups

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults
EPHEMERAL=false
RECREATE_VOLUME=false
BACKUP_ENABLED="${GOFR_BACKUP_ENABLED:-true}"
BOLT_PORT="${GOFR_IQ_NEO4J_BOLT_PORT:-7687}"
HTTP_PORT="${GOFR_IQ_NEO4J_HTTP_PORT:-7474}"
NETWORK="${GOFR_DOCKER_NETWORK:-gofr-net}"
NEO4J_PASSWORD="${GOFR_IQ_NEO4J_PASSWORD:-testpassword}"

CONTAINER_NAME="gofr-iq-neo4j"
IMAGE_NAME="gofr-iq-neo4j:latest"
VOLUME_NAME="gofr-iq-neo4j-data"
BACKUP_VOLUME_NAME="gofr-iq-backups"

# Parse command line arguments
while getopts "erbp:w:n:" opt; do
    case $opt in
        e)
            EPHEMERAL=true
            BACKUP_ENABLED=false
            ;;
        r)
            RECREATE_VOLUME=true
            ;;
        b)
            BACKUP_ENABLED=false
            ;;
        p)
            BOLT_PORT=$OPTARG
            ;;
        w)
            HTTP_PORT=$OPTARG
            ;;
        n)
            NETWORK=$OPTARG
            ;;
        \?)
            echo "Usage: $0 [-e] [-r] [-b] [-p BOLT_PORT] [-w HTTP_PORT] [-n NETWORK]"
            echo "  -e              Ephemeral mode (no persistence)"
            echo "  -r              Recreate volume (fresh database)"
            echo "  -b              Disable backups"
            echo "  -p BOLT_PORT    Bolt port (default: 7687)"
            echo "  -w HTTP_PORT    HTTP port (default: 7474)"
            echo "  -n NETWORK      Docker network to attach to"
            exit 1
            ;;
    esac
done

echo "======================================================================="
echo "Starting Neo4j Server"
echo "======================================================================="
echo "Bolt Port:  $BOLT_PORT"
echo "HTTP Port:  $HTTP_PORT"
echo "Container:  $CONTAINER_NAME"
echo "Mode:       $([ "$EPHEMERAL" = true ] && echo "Ephemeral" || echo "Persistent")"
echo "Backups:    $([ "$BACKUP_ENABLED" = true ] && echo "Enabled (rolling)" || echo "Disabled")"
echo "Network:    $NETWORK"
echo ""

# Build image if it doesn't exist
if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${IMAGE_NAME}$"; then
    echo "Image not found, building..."
    "${SCRIPT_DIR}/build-neo4j.sh"
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
BACKUP_VOLUME_ARGS=""
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

    VOLUME_ARGS="-v ${VOLUME_NAME}:/data"
    
    # Setup backup volume if backups are enabled
    if [ "$BACKUP_ENABLED" = true ]; then
        if ! docker volume inspect "$BACKUP_VOLUME_NAME" >/dev/null 2>&1; then
            echo "Creating backup volume $BACKUP_VOLUME_NAME..."
            docker volume create "$BACKUP_VOLUME_NAME"
        else
            echo "Using existing backup volume $BACKUP_VOLUME_NAME"
        fi
        BACKUP_VOLUME_ARGS="-v ${BACKUP_VOLUME_NAME}:/backups"
    fi
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
echo "Starting Neo4j container..."
docker run -d \
    --name "$CONTAINER_NAME" \
    $NETWORK_ARGS \
    -p "${BOLT_PORT}:7687" \
    -p "${HTTP_PORT}:7474" \
    -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    -e GOFR_BACKUP_ENABLED="$BACKUP_ENABLED" \
    $VOLUME_ARGS \
    $BACKUP_VOLUME_ARGS \
    "$IMAGE_NAME"

# Wait for server to be ready (longer timeout to account for backup)
echo "Waiting for Neo4j to be ready (this may take a minute if backup is running)..."
MAX_ATTEMPTS=180
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    # Check if Neo4j is responding on HTTP
    if curl -sf "http://localhost:${HTTP_PORT}" > /dev/null 2>&1; then
        echo ""
        echo "======================================================================="
        echo "🔷 Neo4j Graph Database"
        echo ""
        echo "Browser:    http://localhost:${HTTP_PORT}"
        echo "Bolt:       bolt://localhost:${BOLT_PORT}"
        echo ""
        echo "Credentials:"
        echo "  Username: neo4j"
        echo "  Password: ${NEO4J_PASSWORD}"
        echo ""
        echo "Storage:    $([ "$EPHEMERAL" = true ] && echo "Ephemeral (in-memory)" || echo "Volume: $VOLUME_NAME")"
        echo "Backups:    $([ "$BACKUP_ENABLED" = true ] && echo "Volume: $BACKUP_VOLUME_NAME" || echo "Disabled")"
        echo ""
        echo "Management:"
        echo "  View logs:  docker logs -f $CONTAINER_NAME"
        echo "  Stop:       ./stop-neo4j.sh"
        echo "  Restart:    ./stop-neo4j.sh && ./start-neo4j.sh"
        echo "======================================================================="
        exit 0
    fi
    ATTEMPT=$((ATTEMPT + 1))
    printf "."
    sleep 1
done

echo ""
echo "ERROR: Neo4j failed to start within ${MAX_ATTEMPTS} seconds"
echo "Note: If backup is running, this may take longer. Check: docker logs $CONTAINER_NAME"
docker logs --tail 20 "$CONTAINER_NAME"
exit 1
