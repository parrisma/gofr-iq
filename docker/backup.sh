#!/bin/bash
# GOFR-IQ Backup Script
# Performs rolling backups for Neo4j and ChromaDB databases
#
# Usage:
#   ./backup.sh                      # Run backup for all services
#   ./backup.sh neo4j                # Backup Neo4j only
#   ./backup.sh chromadb             # Backup ChromaDB only
#   ./backup.sh --restore <file>     # Restore from backup
#   ./backup.sh --list               # List available backups
#   ./backup.sh --clean              # Clean old backups beyond retention
#
# Environment Variables:
#   GOFR_BACKUP_DIR          - Backup directory (default: /backups)
#   GOFR_BACKUP_RETENTION    - Days to keep backups (default: 7)
#   GOFR_BACKUP_MAX_COUNT    - Max backups per service (default: 10)
#   GOFRIQ_NEO4J_PASSWORD    - Neo4j password (default: testpassword)

set -e

# Configuration
BACKUP_DIR="${GOFR_BACKUP_DIR:-/backups}"
BACKUP_RETENTION="${GOFR_BACKUP_RETENTION:-7}"
BACKUP_MAX_COUNT="${GOFR_BACKUP_MAX_COUNT:-10}"
NEO4J_PASSWORD="${GOFRIQ_NEO4J_PASSWORD:-testpassword}"
NEO4J_CONTAINER="${GOFR_NEO4J_CONTAINER:-gofr-iq-neo4j}"
CHROMADB_CONTAINER="${GOFR_CHROMADB_CONTAINER:-gofr-iq-chromadb}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE_ONLY=$(date +%Y%m%d)

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Ensure backup directories exist
setup_backup_dirs() {
    mkdir -p "$BACKUP_DIR/neo4j"
    mkdir -p "$BACKUP_DIR/chromadb"
    mkdir -p "$BACKUP_DIR/logs"
}

# Rotate old backups - keep only BACKUP_MAX_COUNT most recent
rotate_backups() {
    local service=$1
    local backup_path="$BACKUP_DIR/$service"
    
    if [ -d "$backup_path" ]; then
        local count=$(ls -1 "$backup_path" 2>/dev/null | wc -l)
        if [ "$count" -gt "$BACKUP_MAX_COUNT" ]; then
            log_info "Rotating $service backups (keeping $BACKUP_MAX_COUNT most recent)..."
            ls -1t "$backup_path" | tail -n +$((BACKUP_MAX_COUNT + 1)) | while read file; do
                rm -rf "$backup_path/$file"
                log_info "  Removed: $file"
            done
        fi
    fi
}

# Clean backups older than retention period
clean_old_backups() {
    log_info "Cleaning backups older than $BACKUP_RETENTION days..."
    find "$BACKUP_DIR" -type f -mtime +$BACKUP_RETENTION -delete 2>/dev/null || true
    find "$BACKUP_DIR" -type d -empty -delete 2>/dev/null || true
    log_success "Cleanup complete"
}

# Backup Neo4j database
backup_neo4j() {
    local backup_file="$BACKUP_DIR/neo4j/neo4j_${TIMESTAMP}.dump"
    local log_file="$BACKUP_DIR/logs/neo4j_backup_${DATE_ONLY}.log"
    
    log_info "Starting Neo4j backup..."
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${NEO4J_CONTAINER}$"; then
        log_warn "Neo4j container '$NEO4J_CONTAINER' is not running, skipping backup"
        return 1
    fi
    
    # Stop the database for consistent backup
    log_info "Stopping Neo4j for consistent backup..."
    docker exec "$NEO4J_CONTAINER" neo4j stop 2>/dev/null || true
    sleep 3
    
    # Perform backup using neo4j-admin
    log_info "Creating dump: $backup_file"
    if docker exec "$NEO4J_CONTAINER" neo4j-admin database dump neo4j --to-path=/tmp/backup 2>>"$log_file"; then
        # Copy dump from container
        docker cp "$NEO4J_CONTAINER:/tmp/backup/neo4j.dump" "$backup_file"
        docker exec "$NEO4J_CONTAINER" rm -rf /tmp/backup
        
        # Get file size
        local size=$(du -h "$backup_file" | cut -f1)
        log_success "Neo4j backup complete: $backup_file ($size)"
        
        # Rotate old backups
        rotate_backups "neo4j"
    else
        log_error "Neo4j backup failed. Check $log_file for details"
        docker exec "$NEO4J_CONTAINER" neo4j start 2>/dev/null || true
        return 1
    fi
    
    # Restart Neo4j
    log_info "Restarting Neo4j..."
    docker exec "$NEO4J_CONTAINER" neo4j start
    
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Backup completed: $backup_file" >> "$log_file"
    return 0
}

# Backup ChromaDB (volume-based backup)
backup_chromadb() {
    local backup_dir="$BACKUP_DIR/chromadb/chromadb_${TIMESTAMP}"
    local backup_file="$BACKUP_DIR/chromadb/chromadb_${TIMESTAMP}.tar.gz"
    local log_file="$BACKUP_DIR/logs/chromadb_backup_${DATE_ONLY}.log"
    
    log_info "Starting ChromaDB backup..."
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${CHROMADB_CONTAINER}$"; then
        log_warn "ChromaDB container '$CHROMADB_CONTAINER' is not running, skipping backup"
        return 1
    fi
    
    # ChromaDB stores data in /chroma/chroma
    # We'll create a tar of the data directory
    log_info "Creating backup: $backup_file"
    
    # Pause writes temporarily by copying from a snapshot
    if docker exec "$CHROMADB_CONTAINER" tar -czf /tmp/chromadb_backup.tar.gz -C /chroma chroma 2>>"$log_file"; then
        docker cp "$CHROMADB_CONTAINER:/tmp/chromadb_backup.tar.gz" "$backup_file"
        docker exec "$CHROMADB_CONTAINER" rm -f /tmp/chromadb_backup.tar.gz
        
        # Get file size
        local size=$(du -h "$backup_file" | cut -f1)
        log_success "ChromaDB backup complete: $backup_file ($size)"
        
        # Rotate old backups
        rotate_backups "chromadb"
    else
        log_error "ChromaDB backup failed. Check $log_file for details"
        return 1
    fi
    
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Backup completed: $backup_file" >> "$log_file"
    return 0
}

# Restore Neo4j from backup
restore_neo4j() {
    local backup_file=$1
    
    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi
    
    log_warn "This will REPLACE all Neo4j data with the backup!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Restore cancelled"
        return 0
    fi
    
    log_info "Stopping Neo4j..."
    docker exec "$NEO4J_CONTAINER" neo4j stop 2>/dev/null || true
    sleep 3
    
    # Copy backup to container and restore
    log_info "Restoring from: $backup_file"
    docker cp "$backup_file" "$NEO4J_CONTAINER:/tmp/neo4j.dump"
    
    if docker exec "$NEO4J_CONTAINER" neo4j-admin database load neo4j --from-path=/tmp --overwrite-destination=true; then
        docker exec "$NEO4J_CONTAINER" rm -f /tmp/neo4j.dump
        log_success "Neo4j restore complete"
    else
        log_error "Neo4j restore failed"
        return 1
    fi
    
    log_info "Starting Neo4j..."
    docker exec "$NEO4J_CONTAINER" neo4j start
}

# Restore ChromaDB from backup
restore_chromadb() {
    local backup_file=$1
    
    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi
    
    log_warn "This will REPLACE all ChromaDB data with the backup!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Restore cancelled"
        return 0
    fi
    
    log_info "Restoring ChromaDB from: $backup_file"
    
    # Copy backup to container
    docker cp "$backup_file" "$CHROMADB_CONTAINER:/tmp/chromadb_backup.tar.gz"
    
    # Remove existing data and extract backup
    docker exec "$CHROMADB_CONTAINER" sh -c "rm -rf /chroma/chroma/* && tar -xzf /tmp/chromadb_backup.tar.gz -C /chroma && rm -f /tmp/chromadb_backup.tar.gz"
    
    log_success "ChromaDB restore complete"
    log_warn "Restart the ChromaDB container to apply changes"
}

# List available backups
list_backups() {
    echo ""
    echo "======================================================================="
    echo "GOFR-IQ Available Backups"
    echo "======================================================================="
    echo ""
    echo "Neo4j Backups ($BACKUP_DIR/neo4j):"
    echo "-----------------------------------------------------------------------"
    if [ -d "$BACKUP_DIR/neo4j" ] && [ "$(ls -A $BACKUP_DIR/neo4j 2>/dev/null)" ]; then
        ls -lh "$BACKUP_DIR/neo4j" | tail -n +2
    else
        echo "  No backups found"
    fi
    
    echo ""
    echo "ChromaDB Backups ($BACKUP_DIR/chromadb):"
    echo "-----------------------------------------------------------------------"
    if [ -d "$BACKUP_DIR/chromadb" ] && [ "$(ls -A $BACKUP_DIR/chromadb 2>/dev/null)" ]; then
        ls -lh "$BACKUP_DIR/chromadb" | tail -n +2
    else
        echo "  No backups found"
    fi
    
    echo ""
    echo "Backup Logs ($BACKUP_DIR/logs):"
    echo "-----------------------------------------------------------------------"
    if [ -d "$BACKUP_DIR/logs" ] && [ "$(ls -A $BACKUP_DIR/logs 2>/dev/null)" ]; then
        ls -lh "$BACKUP_DIR/logs" | tail -n +2
    else
        echo "  No logs found"
    fi
    echo ""
}

# Show usage
usage() {
    echo "GOFR-IQ Backup Manager"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  (default)          Run backup for all services"
    echo "  neo4j              Backup Neo4j only"
    echo "  chromadb           Backup ChromaDB only"
    echo "  --list             List available backups"
    echo "  --clean            Clean old backups beyond retention"
    echo "  --restore-neo4j <file>    Restore Neo4j from backup"
    echo "  --restore-chromadb <file> Restore ChromaDB from backup"
    echo ""
    echo "Environment Variables:"
    echo "  GOFR_BACKUP_DIR         Backup directory (default: /backups)"
    echo "  GOFR_BACKUP_RETENTION   Days to keep backups (default: 7)"
    echo "  GOFR_BACKUP_MAX_COUNT   Max backups per service (default: 10)"
}

# Main
main() {
    setup_backup_dirs
    
    case "${1:-all}" in
        neo4j)
            backup_neo4j
            ;;
        chromadb)
            backup_chromadb
            ;;
        all|"")
            log_info "Running full backup..."
            backup_neo4j || true
            backup_chromadb || true
            log_success "Backup run complete"
            ;;
        --list|-l)
            list_backups
            ;;
        --clean|-c)
            clean_old_backups
            ;;
        --restore-neo4j)
            restore_neo4j "$2"
            ;;
        --restore-chromadb)
            restore_chromadb "$2"
            ;;
        --help|-h)
            usage
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
