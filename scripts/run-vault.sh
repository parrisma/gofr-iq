#!/bin/bash
# Run Vault Docker container for GOFR-IQ
#
# Usage:
#   ./run-vault.sh           # Default: ephemeral (dev mode)
#   ./run-vault.sh -e        # Ephemeral (no persistence)
#   ./run-vault.sh -p 8201   # Custom port
#
# Dev mode is always ephemeral (in-memory storage)
# Data is lost when container stops

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load centralized port configuration from .env file
GOFR_PORTS_FILE="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
if [ -f "${GOFR_PORTS_FILE}" ]; then
    set -a  # automatically export all variables
    source "${GOFR_PORTS_FILE}"
    set +a
else
    echo "ERROR: Port configuration file not found: ${GOFR_PORTS_FILE}" >&2
    exit 1
fi

# Defaults (from gofr_ports.sh)
IMAGE_NAME="gofr-iq-vault"
IMAGE_TAG="latest"
CONTAINER_NAME="gofr-vault"
HOSTNAME="gofr-vault"
NETWORK="gofr-net"
PORT="${GOFR_VAULT_PORT}"
ROOT_TOKEN="${GOFR_VAULT_DEV_TOKEN}"
EPHEMERAL=true  # Dev mode is always ephemeral

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -e, --ephemeral     Ephemeral mode (default, dev mode is always ephemeral)"
    echo "  -p, --port PORT     Host port to expose (default: ${PORT})"
    echo "  -t, --token TOKEN   Root token (default: ${ROOT_TOKEN})"
    echo "  -n, --network NET   Docker network (default: ${NETWORK})"
    echo "  -h, --help          Show this help"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--ephemeral)
            EPHEMERAL=true
            shift
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -t|--token)
            ROOT_TOKEN="$2"
            shift 2
            ;;
        -n|--network)
            NETWORK="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            exit 1
            ;;
    esac
done

echo "======================================================================="
echo "Starting GOFR-IQ Vault Container"
echo "======================================================================="
echo "Image:      ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Container:  ${CONTAINER_NAME}"
echo "Port:       ${PORT}:8200"
echo "Network:    ${NETWORK}"
echo "Mode:       Dev (ephemeral, in-memory)"
echo "Root Token: ${ROOT_TOKEN}"
echo "======================================================================="

# Check if image exists
if ! docker image inspect "${IMAGE_NAME}:${IMAGE_TAG}" >/dev/null 2>&1; then
    echo -e "${YELLOW}Image not found. Building...${NC}"
    "${SCRIPT_DIR}/build-vault.sh"
fi

# Create network if needed
if ! docker network inspect ${NETWORK} >/dev/null 2>&1; then
    echo "Creating network: ${NETWORK}"
    docker network create ${NETWORK}
fi

# Stop existing container if running
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping existing container..."
    docker stop ${CONTAINER_NAME} >/dev/null 2>&1 || true
    docker rm ${CONTAINER_NAME} >/dev/null 2>&1 || true
fi

# Run container
echo "Starting container..."
docker run -d \
    --name ${CONTAINER_NAME} \
    --hostname ${HOSTNAME} \
    --network ${NETWORK} \
    --cap-add IPC_LOCK \
    -p ${PORT}:8200 \
    -e VAULT_DEV_ROOT_TOKEN_ID="${ROOT_TOKEN}" \
    -e VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200 \
    -e VAULT_ADDR=http://127.0.0.1:8200 \
    ${IMAGE_NAME}:${IMAGE_TAG}

# Wait for Vault to be ready
echo -n "Waiting for Vault to be ready"
for i in {1..30}; do
    if docker exec ${CONTAINER_NAME} vault status >/dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
        break
    fi
    echo -n "."
    sleep 1
done

# Check if ready
if docker exec ${CONTAINER_NAME} vault status >/dev/null 2>&1; then
    echo ""
    echo -e "${GREEN}=======================================================================${NC}"
    echo -e "${GREEN}Vault is running!${NC}"
    echo -e "${GREEN}=======================================================================${NC}"
    echo ""
    echo "Access from host:"
    echo "  VAULT_ADDR=http://localhost:${PORT}"
    echo "  VAULT_TOKEN=${ROOT_TOKEN}"
    echo ""
    echo "Access from other containers on ${NETWORK}:"
    echo "  VAULT_ADDR=http://${HOSTNAME}:8200"
    echo "  VAULT_TOKEN=${ROOT_TOKEN}"
    echo ""
    echo "To stop: docker stop ${CONTAINER_NAME}"
else
    echo -e " ${RED}✗${NC}"
    echo -e "${RED}Vault failed to start. Checking logs...${NC}"
    docker logs ${CONTAINER_NAME} 2>&1 | tail -20
    exit 1
fi
