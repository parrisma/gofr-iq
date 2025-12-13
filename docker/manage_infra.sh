#!/bin/bash
# GOFR-IQ Infrastructure Management
# Start/stop/restart all infrastructure containers (ChromaDB, Neo4j)
# Includes automatic rolling backup management
#
# Usage: 
#   ./manage_infra.sh start [--test]     # Start infrastructure (--test for ephemeral)
#   ./manage_infra.sh stop [--test]      # Stop infrastructure
#   ./manage_infra.sh restart [--test]   # Restart infrastructure
#   ./manage_infra.sh status             # Show status of all containers
#   ./manage_infra.sh logs [service]     # Show logs (chromadb, neo4j, or all)
#   ./manage_infra.sh clean              # Stop and remove all volumes
#   ./manage_infra.sh backup             # Run backup for all services
#   ./manage_infra.sh backup-list        # List available backups
#   ./manage_infra.sh restore <service> <file>  # Restore from backup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default compose file
COMPOSE_FILE="docker-compose.yml"
TEST_MODE=false

# Parse arguments
ACTION="${1:-status}"
shift || true

while [[ $# -gt 0 ]]; do
    case $1 in
        --test|-t)
            TEST_MODE=true
            COMPOSE_FILE="docker-compose.test.yml"
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
    local network_name="$1"
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
    echo ""
    
    # Ensure network exists
    if [ "$TEST_MODE" = true ]; then
        ensure_network "gofr-test-net"
    else
        ensure_network "gofr-net"
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
    docker compose -f "$COMPOSE_FILE" down
    
    log_success "Infrastructure stopped"
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
    
    # Show containers
    if [ "$TEST_MODE" = true ]; then
        docker ps -a --filter "name=gofr-iq-.*-test" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        docker ps -a --filter "name=gofr-iq-chromadb" --filter "name=gofr-iq-neo4j" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -v "\-test"
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
        docker compose -f docker-compose.yml down -v 2>/dev/null || true
        docker compose -f docker-compose.test.yml down -v 2>/dev/null || true
        
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
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|clean|backup|backup-list|restore} [--test]"
        echo ""
        echo "Commands:"
        echo "  start        Start infrastructure containers"
        echo "  stop         Stop infrastructure containers"
        echo "  restart      Restart infrastructure containers"
        echo "  status       Show status of containers"
        echo "  logs         Show container logs (optionally specify service)"
        echo "  clean        Remove all containers and volumes"
        echo "  backup       Run backup for all services (or specify: neo4j, chromadb)"
        echo "  backup-list  List available backups"
        echo "  restore      Restore from backup: restore <neo4j|chromadb> <file>"
        echo ""
        echo "Options:"
        echo "  --test    Use ephemeral test containers (no backups)"
        exit 1
        ;;
esac
