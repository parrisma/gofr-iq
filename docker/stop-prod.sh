#!/bin/bash
# Stop GOFR-IQ production stack gracefully.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILE="${PROJECT_ROOT}/docker/compose.prod.yml"
PORTS_ENV="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"

# Source ports so docker compose can resolve variables
if [ -f "${PORTS_ENV}" ]; then
  set -a
  # shellcheck disable=SC1090
  source "${PORTS_ENV}"
  set +a
fi

echo "Stopping GOFR-IQ production stack..."

docker compose -f "${COMPOSE_FILE}" down "$@"

echo "Stack stopped"
