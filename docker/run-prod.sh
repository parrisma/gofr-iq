#!/bin/bash
# Run gofr-iq production container with proper volumes and networking
set -e

CONTAINER_NAME="gofr-iq-prod"
IMAGE_NAME="gofr-iq-prod:latest"
NETWORK_NAME="gofr-net"

source "$(dirname "$0")/../lib/gofr-common/config/gofr_ports.sh"
MCP_PORT="${GOFR_IQ_MCP_PORT}"
MCPO_PORT="${GOFR_IQ_MCPO_PORT}"
WEB_PORT="${GOFR_IQ_WEB_PORT}"

# JWT Secret and Auth Configuration
JWT_SECRET="${GOFR_IQ_JWT_SECRET:-}"
AUTH_DISABLED="${GOFR_IQ_AUTH_DISABLED:-false}"

if [ "$AUTH_DISABLED" = "false" ] && [ -z "$JWT_SECRET" ]; then
    echo "ERROR: GOFR_IQ_JWT_SECRET environment variable is required OR set GOFR_IQ_AUTH_DISABLED=true"
    echo "Usage: GOFR_IQ_JWT_SECRET=your-secret ./run-prod.sh"
    echo "   OR: GOFR_IQ_AUTH_DISABLED=true ./run-prod.sh"
    exit 1
fi

# Neo4j connection (optional)
NEO4J_URI="${NEO4J_URI:-bolt://gofr-neo4j:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"

# ChromaDB connection (from gofr_ports.sh)
CHROMA_HOST="${CHROMA_HOST:-gofr-chroma}"
CHROMA_PORT="${GOFR_CHROMA_PORT}"

echo "=== gofr-iq Production Container ==="

# Create network if it doesn't exist
if ! docker network inspect ${NETWORK_NAME} >/dev/null 2>&1; then
    echo "Creating network: ${NETWORK_NAME}"
    docker network create ${NETWORK_NAME}
fi

# Create volumes if they don't exist
for vol in gofr-iq-data gofr-iq-logs; do
    if ! docker volume inspect ${vol} >/dev/null 2>&1; then
        echo "Creating volume: ${vol}"
        docker volume create ${vol}
    fi
done

# Stop existing container if running
if docker ps -q -f name=${CONTAINER_NAME} | grep -q .; then
    echo "Stopping existing container..."
    docker stop ${CONTAINER_NAME}
fi

# Remove existing container if exists
if docker ps -aq -f name=${CONTAINER_NAME} | grep -q .; then
    echo "Removing existing container..."
    docker rm ${CONTAINER_NAME}
fi

echo "Starting ${CONTAINER_NAME}..."
echo "  MCP Port:  ${MCP_PORT}"
echo "  MCPO Port: ${MCPO_PORT}"
echo "  Web Port:  ${WEB_PORT}"

docker run -d \
    --name ${CONTAINER_NAME} \
    --network ${NETWORK_NAME} \
    -v gofr-iq-data:/home/gofr-iq/data \
    -v gofr-iq-logs:/home/gofr-iq/logs \
    -p ${MCP_PORT}:${MCP_PORT} \
    -p ${MCPO_PORT}:${MCPO_PORT} \
    -p ${WEB_PORT}:${WEB_PORT} \
    -e JWT_SECRET="${JWT_SECRET}" \
    -e GOFR_IQ_AUTH_DISABLED="${AUTH_DISABLED}" \
    -e GOFR_IQ_MCP_PORT=${MCP_PORT} \
    -e GOFR_IQ_MCPO_PORT=${MCPO_PORT} \
    -e GOFR_IQ_WEB_PORT=${WEB_PORT} \
    -e NEO4J_URI="${NEO4J_URI}" \
    -e NEO4J_USER="${NEO4J_USER}" \
    -e NEO4J_PASSWORD="${NEO4J_PASSWORD}" \
    -e CHROMA_HOST="${CHROMA_HOST}" \
    -e CHROMA_PORT="${CHROMA_PORT}" \
    ${IMAGE_NAME}

# Wait for container to start
sleep 2

if docker ps -q -f name=${CONTAINER_NAME} | grep -q .; then
    echo ""
    echo "=== Container Started Successfully ==="
    echo "MCP Server:  http://localhost:${MCP_PORT}/mcp"
    echo "MCPO Server: http://localhost:${MCPO_PORT}"
    echo "Web Server:  http://localhost:${WEB_PORT}"
    echo ""
    echo "Volumes:"
    echo "  Data: gofr-iq-data"
    echo "  Logs: gofr-iq-logs"
    echo ""
    echo "Commands:"
    echo "  Logs:   docker logs -f ${CONTAINER_NAME}"
    echo "  Stop:   ./stop-prod.sh"
    echo "  Shell:  docker exec -it ${CONTAINER_NAME} bash"
else
    echo "ERROR: Container failed to start"
    docker logs ${CONTAINER_NAME}
    exit 1
fi
