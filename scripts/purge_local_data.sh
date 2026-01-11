#!/bin/bash
# =============================================================================
# Purge Local Data Directories
# =============================================================================
# Clears local data and test/data directories.
#
# Production data should be stored in Docker volumes, not local directories.
# Test data should be cleared between test runs.
#
# By default, only test/data is purged (safe for development).
# Use --all to also purge data/ directories.
#
# This script can remove:
#   - test/data/*        (test artifacts) - DEFAULT
#   - data/auth/*        (file-based auth - should use Vault)
#   - data/sessions/*    (session data)
#   - data/storage/*     (document storage)
#
# It preserves:
#   - .gitkeep files
#   - Directory structure
#
# Usage:
#   ./scripts/purge_local_data.sh              # Default: purge test/data only
#   ./scripts/purge_local_data.sh --test-only  # Same as default
#   ./scripts/purge_local_data.sh --all        # Purge all data directories
#   ./scripts/purge_local_data.sh --force      # No confirmation
#   ./scripts/purge_local_data.sh --dry-run    # Show what would be deleted
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
FORCE=false
DRY_RUN=false
PURGE_ALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --force|-f)
            FORCE=true
            shift
            ;;
        --dry-run|-n)
            DRY_RUN=true
            shift
            ;;
        --all|-a)
            PURGE_ALL=true
            shift
            ;;
        --test-only|-t)
            PURGE_ALL=false
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--test-only|-t] [--all|-a] [--force|-f] [--dry-run|-n]"
            echo ""
            echo "Options:"
            echo "  --test-only, -t  Only purge test/data (DEFAULT)"
            echo "  --all, -a        Purge all data directories (data/ and test/data/)"
            echo "  --force, -f      Skip confirmation prompt"
            echo "  --dry-run, -n    Show what would be deleted without deleting"
            echo "  --help, -h       Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Directories to purge based on mode
if [[ "$PURGE_ALL" == true ]]; then
    PURGE_DIRS=(
        "data/auth"
        "data/sessions"
        "data/storage"
        "test/data"
    )
    MODE_DESC="all data"
else
    PURGE_DIRS=(
        "test/data"
    )
    MODE_DESC="test data only"
fi

echo -e "${YELLOW}=== Purge Local Data (${MODE_DESC}) ===${NC}"
echo "Project root: ${PROJECT_ROOT}"
echo ""

# Show what will be deleted
echo "Directories to purge:"
total_files=0
total_size=0

for dir in "${PURGE_DIRS[@]}"; do
    full_path="${PROJECT_ROOT}/${dir}"
    if [[ -d "$full_path" ]]; then
        # Count files (excluding .gitkeep)
        file_count=$(find "$full_path" -type f ! -name ".gitkeep" 2>/dev/null | wc -l)
        # Get size
        dir_size=$(du -sh "$full_path" 2>/dev/null | cut -f1)
        echo "  ${dir}/ - ${file_count} files, ${dir_size}"
        total_files=$((total_files + file_count))
    else
        echo "  ${dir}/ - (not found)"
    fi
done

echo ""
echo "Total files to delete: ${total_files}"

if [[ $total_files -eq 0 ]]; then
    echo -e "${GREEN}Nothing to purge.${NC}"
    exit 0
fi

# Dry run - just show, don't delete
if [[ "$DRY_RUN" == true ]]; then
    echo ""
    echo -e "${YELLOW}Dry run - would delete:${NC}"
    for dir in "${PURGE_DIRS[@]}"; do
        full_path="${PROJECT_ROOT}/${dir}"
        if [[ -d "$full_path" ]]; then
            find "$full_path" -type f ! -name ".gitkeep" 2>/dev/null | head -20
            remaining=$(find "$full_path" -type f ! -name ".gitkeep" 2>/dev/null | wc -l)
            if [[ $remaining -gt 20 ]]; then
                echo "  ... and $((remaining - 20)) more files"
            fi
        fi
    done
    exit 0
fi

# Confirm unless --force
if [[ "$FORCE" != true ]]; then
    echo ""
    echo -e "${RED}WARNING: This will permanently delete local data files.${NC}"
    echo "Production data should be in Docker volumes (Vault, ChromaDB, Neo4j)."
    echo ""
    read -p "Are you sure you want to continue? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Purge each directory
echo ""
echo "Purging..."

for dir in "${PURGE_DIRS[@]}"; do
    full_path="${PROJECT_ROOT}/${dir}"
    if [[ -d "$full_path" ]]; then
        # Delete all files except .gitkeep
        find "$full_path" -type f ! -name ".gitkeep" -delete 2>/dev/null || true
        # Delete empty subdirectories
        find "$full_path" -mindepth 1 -type d -empty -delete 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} ${dir}/"
    fi
done

echo ""
echo -e "${GREEN}=== Purge Complete ===${NC}"
echo ""
echo "Note: Production data is stored in Docker volumes:"
echo "  - Vault:    gofr-vault-data"
echo "  - ChromaDB: gofr-iq-chroma-data"
echo "  - Neo4j:    gofr-iq-neo4j-data"
