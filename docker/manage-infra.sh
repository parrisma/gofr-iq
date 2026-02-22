#!/bin/bash
# GOFR-IQ Infrastructure Management
# Start/stop/restart all infrastructure containers (Vault, ChromaDB, Neo4j)
# Includes automatic rolling backup management
#
# Usage: 
#   ./manage_infra.sh start [--test]     # Start infrastructure (--test for ephemeral)
#   ./manage_infra.sh stop [--test]      # Stop infrastructure
#   ./manage_infra.sh restart [--test]   # Restart infrastructure
#   ./manage_infra.sh status             # Show status of all containers
#   ./manage_infra.sh logs [service]     # Show logs (vault, chromadb, neo4j, or all)
#   ./manage_infra.sh clean              # Stop and remove all volumes
#   ./manage_infra.sh backup             # Run backup for all services
#   ./manage_infra.sh backup-list        # List available backups
#   ./manage_infra.sh restore <service> <file>  # Restore from backup
#   ./manage_infra.sh vault [--test]     # Start only Vault container

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

# Source centralized port configuration from .env file
# BUT: If ports are already set (e.g., from run_tests.sh with +100 offset), don't override
GOFR_PORTS_FILE="$PROJECT_ROOT/lib/gofr-common/config/gofr_ports.env"
if [ -z "$GOFR_IQ_MCP_PORT" ]; then
    # Ports not set - load from config file
    if [ -f "$GOFR_PORTS_FILE" ]; then
        set -a
        source "$GOFR_PORTS_FILE"
        set +a
    else
        echo "ERROR: Port configuration file not found: $GOFR_PORTS_FILE" >&2
        exit 1
    fi
else
    # Ports already set (likely from test runner) - use them
    : # no-op
fi

# Load secrets from gofr-common/.env if not already set
GOFR_COMMON_ENV="$PROJECT_ROOT/lib/gofr-common/.env"
if [ -f "$GOFR_COMMON_ENV" ]; then
    # Only load if vars not already set (don't override test runner settings)
    if [ -z "$GOFR_JWT_SECRET" ] || [ -z "$GOFR_VAULT_DEV_TOKEN" ]; then
        set -a
        source "$GOFR_COMMON_ENV"
        set +a
    fi
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default compose file
COMPOSE_FILE="compose.prod.yml"
TEST_MODE=false
NETWORK_NAME="gofr-net"

# Parse arguments
ACTION="${1:-status}"
shift || true

while [[ $# -gt 0 ]]; do
    case $1 in
        --test|-t)
            TEST_MODE=true
            COMPOSE_FILE="compose.dev.yml"
            NETWORK_NAME="gofr-test-net"
            # Switch to test ports (prod + 100)
            export GOFR_VAULT_PORT="${GOFR_VAULT_PORT_TEST:-$((GOFR_VAULT_PORT + 100))}"
            export GOFR_CHROMA_PORT="${GOFR_CHROMA_PORT_TEST:-$((GOFR_CHROMA_PORT + 100))}"
            export GOFR_NEO4J_HTTP_PORT="${GOFR_NEO4J_HTTP_PORT_TEST:-$((GOFR_NEO4J_HTTP_PORT + 100))}"
            export GOFR_NEO4J_BOLT_PORT="${GOFR_NEO4J_BOLT_PORT_TEST:-$((GOFR_NEO4J_BOLT_PORT + 100))}"
            shift
            ;;
        *)
            SERVICE="$1"
            shift
            ;;
    esac
done

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

ensure_network() {
    local network_name="${1:-$NETWORK_NAME}"
    if ! docker network inspect "$network_name" >/dev/null 2>&1; then
        log_info "Creating network: $network_name"
        docker network create "$network_name"
    fi
}

wait_for_healthy() {
    local container="$1"
    local max_wait="${2:-120}"
    local elapsed=0
    
    log_info "Waiting for $container to be healthy..."
    while [ $elapsed -lt $max_wait ]; do
        local health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")
        case "$health" in
            healthy)
                log_success "$container is healthy"
                return 0
                ;;
            unhealthy)
                log_error "$container is unhealthy"
                docker logs --tail 20 "$container"
                return 1
                ;;
            not_found)
                log_error "$container not found"
                return 1
                ;;
        esac
        sleep 2
        elapsed=$((elapsed + 2))
        printf "."
    done
    echo
    log_error "$container did not become healthy within ${max_wait}s"
    return 1
}

do_start() {
    echo "======================================================================="
    echo "Starting GOFR-IQ Infrastructure"
    echo "======================================================================="
    echo "Mode: $([ "$TEST_MODE" = true ] && echo "TEST (ephemeral)" || echo "DEVELOPMENT (persistent)")"
    echo "Compose file: $COMPOSE_FILE"
    echo "Network: $NETWORK_NAME"
    echo "Ports:"
    echo "  Vault:    ${GOFR_VAULT_PORT}"
    echo "  Neo4j:    HTTP=${GOFR_NEO4J_HTTP_PORT} Bolt=${GOFR_NEO4J_BOLT_PORT}"
    echo "  ChromaDB: ${GOFR_CHROMA_PORT}"
    echo "  MCP:      ${GOFR_IQ_MCP_PORT}"
    echo "  MCPO:     ${GOFR_IQ_MCPO_PORT}"
    echo "  Web:      ${GOFR_IQ_WEB_PORT}"
    echo ""
    
    # Ensure network exists
    ensure_network "$NETWORK_NAME"
    
    # For non-test mode, start Vault separately (test mode includes vault in compose)
    if [ "$TEST_MODE" = false ]; then
        do_vault_start
    fi
    
    # Build images if needed
    log_info "Building images..."
    docker compose -f "$COMPOSE_FILE" build
    
    # Start services
    log_info "Starting services..."
    docker compose -f "$COMPOSE_FILE" up -d
    
    # Wait for health
    echo ""
    if [ "$TEST_MODE" = true ]; then
        wait_for_healthy "gofr-iq-chromadb-test" 60
        wait_for_healthy "gofr-iq-neo4j-test" 90
    else
        wait_for_healthy "gofr-iq-chromadb" 60
        wait_for_healthy "gofr-iq-neo4j" 90
    fi
    
    echo ""
    echo "======================================================================="
    log_success "Infrastructure started successfully"
    echo "======================================================================="
    do_status
}

do_stop() {
    echo "======================================================================="
    echo "Stopping GOFR-IQ Infrastructure"
    echo "======================================================================="
    
    log_info "Stopping services..."
    
    if [ "$TEST_MODE" = true ]; then
        # In test mode, use -v to remove anonymous volumes and keep system clean
        docker compose -f "$COMPOSE_FILE" down -v
    else
        docker compose -f "$COMPOSE_FILE" down
    fi
    
    # Stop Vault separately only in non-test mode (test mode vault is in compose)
    if [ "$TEST_MODE" = false ]; then
        do_vault_stop
    fi
    
    log_success "Infrastructure stopped"
}

do_vault_start() {
    log_info "Starting Vault on port ${GOFR_VAULT_PORT}..."
    
    # Use gofr-common Vault management
    local vault_script="$SCRIPT_DIR/../lib/gofr-common/scripts/manage_vault.sh"
    if [ -f "$vault_script" ]; then
        # Export port vars for the script
        export GOFR_VAULT_PORT
        export GOFR_VAULT_DEV_TOKEN

        # manage_vault.sh requires an explicit subcommand.
        # NOTE: It currently manages its own network (gofr-net) and does not
        # accept a --network argument.
        bash "$vault_script" start
    else
        log_warn "Vault run script not found at $vault_script, skipping..."
    fi
}

do_vault_stop() {
    log_info "Stopping Vault..."
    # Stop vault container
    if [ "$TEST_MODE" = true ]; then
        docker stop gofr-vault-test 2>/dev/null || true
        docker rm gofr-vault-test 2>/dev/null || true
    else
        docker stop gofr-vault 2>/dev/null || true
        docker rm gofr-vault 2>/dev/null || true
    fi
}

do_restart() {
    do_stop
    echo ""
    do_start
}

do_status() {
    echo ""
    echo "GOFR-IQ Infrastructure Status"
    echo "======================================================================="
    echo "Mode: $([ "$TEST_MODE" = true ] && echo "TEST" || echo "PRODUCTION")"
    echo ""
    
    # Show containers
    if [ "$TEST_MODE" = true ]; then
        docker ps -a --filter "name=gofr.*-test" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        docker ps -a --filter "name=gofr-iq-chromadb" --filter "name=gofr-iq-neo4j" --filter "name=gofr-vault" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -v "\-test" || true
    fi
    
    echo ""
    echo "Volumes:"
    docker volume ls --filter "name=gofr-iq" --format "table {{.Name}}\t{{.Driver}}"
    
    echo ""
    echo "Networks:"
    docker network ls --filter "name=gofr" --format "table {{.Name}}\t{{.Driver}}"
}

do_logs() {
    local service="${SERVICE:-}"
    
    if [ -z "$service" ]; then
        docker compose -f "$COMPOSE_FILE" logs -f
    else
        docker compose -f "$COMPOSE_FILE" logs -f "$service"
    fi
}

do_clean() {
    echo "======================================================================="
    echo "Cleaning GOFR-IQ Infrastructure"
    echo "======================================================================="
    log_warn "This will remove all containers and volumes!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Stopping and removing containers..."
        docker compose -f compose.prod.yml down -v 2>/dev/null || true
        docker compose -f compose.dev.yml down -v 2>/dev/null || true
        
        # Stop vault containers
        docker stop gofr-vault gofr-vault-test 2>/dev/null || true
        docker rm gofr-vault gofr-vault-test 2>/dev/null || true
        
        log_info "Removing orphan volumes..."
        docker volume ls -q --filter "name=gofr-iq" | xargs -r docker volume rm 2>/dev/null || true
        
        log_success "Cleanup complete"
    else
        log_info "Cleanup cancelled"
    fi
}

do_backup() {
    echo "======================================================================="
    echo "Running GOFR-IQ Backup"
    echo "======================================================================="
    
    if [ -f "$SCRIPT_DIR/backup.sh" ]; then
        bash "$SCRIPT_DIR/backup.sh" "${SERVICE:-all}"
    else
        log_error "Backup script not found: $SCRIPT_DIR/backup.sh"
        exit 1
    fi
}

do_backup_list() {
    if [ -f "$SCRIPT_DIR/backup.sh" ]; then
        bash "$SCRIPT_DIR/backup.sh" --list
    else
        log_error "Backup script not found: $SCRIPT_DIR/backup.sh"
        exit 1
    fi
}

do_restore() {
    local service="${1:-}"
    local backup_file="${2:-}"
    
    if [ -z "$service" ] || [ -z "$backup_file" ]; then
        log_error "Usage: $0 restore <neo4j|chromadb> <backup_file>"
        exit 1
    fi
    
    echo "======================================================================="
    echo "Restoring GOFR-IQ $service from backup"
    echo "======================================================================="
    
    if [ -f "$SCRIPT_DIR/backup.sh" ]; then
        bash "$SCRIPT_DIR/backup.sh" "--restore-$service" "$backup_file"
    else
        log_error "Backup script not found: $SCRIPT_DIR/backup.sh"
        exit 1
    fi
}

# Main
case "$ACTION" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_restart
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    clean)
        do_clean
        ;;
    backup)
        do_backup
        ;;
    backup-list)
        do_backup_list
        ;;
    restore)
        do_restore "$SERVICE" "$2"
        ;;
    vault)
        do_vault_start
        ;;
    vault-stop)
        do_vault_stop
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|clean|backup|backup-list|restore|vault|vault-stop} [--test]"
        echo ""
        echo "Commands:"
        echo "  start        Start infrastructure containers (Vault, ChromaDB, Neo4j)"
        echo "  stop         Stop infrastructure containers"
        echo "  restart      Restart infrastructure containers"
        echo "  status       Show status of containers"
        echo "  logs         Show container logs (optionally specify service)"
        echo "  clean        Remove all containers and volumes"
        echo "  backup       Run backup for all services (or specify: neo4j, chromadb)"
        echo "  backup-list  List available backups"
        echo "  restore      Restore from backup: restore <neo4j|chromadb> <file>"
        echo "  vault        Start only Vault container"
        echo "  vault-stop   Stop only Vault container"
        echo ""
        echo "Options:"
        echo "  --test    Use ephemeral test containers (no backups)"
        exit 1
        ;;
esac
