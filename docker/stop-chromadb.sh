#!/bin/bash
# Stop ChromaDB server for GOFR-IQ
#
# Usage: ./stop-chromadb.sh [-v]
# Options:
#   -v    Also remove the data volume (WARNING: deletes all data)

set -e

CONTAINER_NAME="gofr-iq-chromadb"
VOLUME_NAME="gofr-iq-chromadb-data"

# Parse command line arguments
REMOVE_VOLUME=false
while getopts "v" opt; do
    case $opt in
        v)
            REMOVE_VOLUME=true
            ;;
        \?)
            echo "Usage: $0 [-v]"
            echo "  -v    Also remove the data volume"
            exit 1
            ;;
    esac
done

echo "======================================================================="
echo "Stopping ChromaDB Server"
echo "======================================================================="

# Stop and remove container
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping container..."
    docker stop "$CONTAINER_NAME" > /dev/null
    echo "Removing container..."
    docker rm "$CONTAINER_NAME" > /dev/null
    echo "ChromaDB stopped"
elif docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Removing stopped container..."
    docker rm "$CONTAINER_NAME" > /dev/null
    echo "ChromaDB container removed"
else
    echo "ChromaDB container not found (not running)"
fi

# Optionally remove volume
if [ "$REMOVE_VOLUME" = true ]; then
    if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
        echo "Removing data volume..."
        docker volume rm "$VOLUME_NAME" > /dev/null
        echo "Volume $VOLUME_NAME removed"
    else
        echo "Volume $VOLUME_NAME not found"
    fi
fi

echo ""
echo "Done"
