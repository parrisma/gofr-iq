#!/bin/bash
# ChromaDB Entrypoint with Automatic Backup on Startup
# This script runs a backup of existing data before starting ChromaDB
#
# Backup behavior:
#   - Creates a rolling backup on container start (if data exists)
#   - Maintains configurable retention policy
#   - Stores backups in mounted /backups volume

set -euo pipefail

BACKUP_DIR="${GOFR_BACKUP_DIR:-/backups}"
BACKUP_ENABLED="${GOFR_BACKUP_ENABLED:-true}"
BACKUP_ON_STARTUP="${GOFR_BACKUP_ON_STARTUP:-true}"
BACKUP_RETENTION="${GOFR_BACKUP_RETENTION:-7}"
BACKUP_MAX_COUNT="${GOFR_BACKUP_MAX_COUNT:-10}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
log_info() { echo -e "${BLUE}[BACKUP]${NC} [$(timestamp)] $1"; }
log_success() { echo -e "${GREEN}[BACKUP]${NC} [$(timestamp)] $1"; }
log_warn() { echo -e "${YELLOW}[BACKUP]${NC} [$(timestamp)] $1"; }
log_error() { echo -e "${YELLOW}[BACKUP]${NC} [$(timestamp)] $1" >&2; }

trap 'log_error "Entrypoint failed at line $LINENO"' ERR

# Setup backup directories
setup_backup() {
    if [ "$BACKUP_ENABLED" = "true" ]; then
        mkdir -p "$BACKUP_DIR/chromadb"
        mkdir -p "$BACKUP_DIR/logs"
        log_info "Backup directory: $BACKUP_DIR/chromadb"
    fi
}

# Rotate old backups
rotate_backups() {
    local backup_path="$BACKUP_DIR/chromadb"

    if [ -d "$backup_path" ]; then
        # Remove backups older than retention period
        find "$backup_path" -type f -name "*.tar.gz" -mtime +$BACKUP_RETENTION -delete 2>/dev/null || true
        
        # Keep only max count backups
        local count
        count=$(ls -1 "$backup_path"/*.tar.gz 2>/dev/null | wc -l | tr -d ' ')
        if [ "${count:-0}" -gt "$BACKUP_MAX_COUNT" ]; then
            log_info "Rotating backups (keeping $BACKUP_MAX_COUNT most recent)..."
            ls -1t "$backup_path"/*.tar.gz | tail -n +$((BACKUP_MAX_COUNT + 1)) | xargs rm -f 2>/dev/null || true
        fi
    fi
}

# Create backup of existing data
create_startup_backup() {
    if [ "$BACKUP_ENABLED" != "true" ] || [ "$BACKUP_ON_STARTUP" != "true" ]; then
        log_info "Startup backup disabled"
        return 0
    fi
    
    # Check if there's existing data to backup
    local data_dir="/chroma/chroma"
    if [ ! -d "$data_dir" ] || [ ! "$(ls -A $data_dir 2>/dev/null)" ]; then
        log_info "No existing ChromaDB data found, skipping startup backup"
        return 0
    fi
    
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/chromadb/chromadb_startup_${timestamp}.tar.gz"
    local log_file="$BACKUP_DIR/logs/chromadb_backup.log"
    
    log_info "Creating startup backup of existing data..."
    
    if tar -czf "$backup_file" -C /chroma chroma 2>>"$log_file"; then
        local size=$(du -h "$backup_file" | cut -f1)
        log_success "Startup backup complete: chromadb_startup_${timestamp}.tar.gz ($size)"
        
        # Record in log
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Startup backup: $backup_file" >> "$log_file"
        
        # Rotate old backups
        rotate_backups
    else
        log_warn "Startup backup failed"
    fi
}

# Main entrypoint
main() {
    echo "======================================================================="
    echo "ChromaDB Container with Rolling Backup Support"
    echo "======================================================================="
    echo "Backup Enabled:    $BACKUP_ENABLED"
    echo "Backup on Startup: $BACKUP_ON_STARTUP"
    echo "Backup Retention:  $BACKUP_RETENTION days"
    echo "Max Backups:       $BACKUP_MAX_COUNT"
    echo "======================================================================="
    
    # Setup and run backup
    setup_backup
    create_startup_backup
    
    echo ""
    echo "Starting ChromaDB..."
    
    # ChromaDB doesn't have a specific entrypoint script, 
    # it uses uvicorn directly. Execute the default command.
    exec "$@"
}

main "$@"
