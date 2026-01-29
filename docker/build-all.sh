#!/bin/bash
# Build all GOFR-IQ images (dev and/or prod stacks)
#
# Usage:
#   ./build-all.sh [--dev] [--prod] [--force|--update]
#     --dev     : build development image only
#     --prod    : build production stack (base tag + infra + prod)
#     --force   : build all requested images regardless of cache/staleness
#     --update  : only build if image missing or Dockerfile is newer (default)
#   (no flags): build both dev and prod stacks with --update behavior

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEV=false
PROD=false
FORCE=false
UPDATE=true

usage() {
    cat <<'EOF'
Build GOFR-IQ images via existing per-image scripts.

Options:
    --dev     Build dev image only (gofr-iq-dev)
    --prod    Build prod stack: tag gofr-iq-base, infra (ChromaDB, Neo4j, Vault), then gofr-iq-prod
    --force   Force build even if images exist and Dockerfiles are unchanged
    --update  Build only when missing or Dockerfile is newer than the image (default)
  -h|--help Show this help

Examples:
  ./build-all.sh          # Build dev + prod stacks
  ./build-all.sh --dev    # Build dev only
  ./build-all.sh --prod   # Build prod stack only
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dev)
            DEV=true
            ;;
        --prod)
            PROD=true
            ;;
        --force)
            FORCE=true
            UPDATE=false
            ;;
        --update)
            UPDATE=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
    shift
done

if ! $DEV && ! $PROD; then
    DEV=true
    PROD=true
fi

should_build() {
    local image="$1"
    local dockerfile="$2"

    if $FORCE; then
        return 0
    fi

    if ! $UPDATE; then
        return 0
    fi

    if ! docker image inspect "$image" >/dev/null 2>&1; then
        return 0
    fi

    if [ ! -f "$dockerfile" ]; then
        return 0
    fi

    local df_ts image_created image_ts
    df_ts=$(stat -c %Y "$dockerfile" 2>/dev/null || echo 0)
    image_created=$(docker image inspect "$image" -f '{{.Created}}' 2>/dev/null || echo "")
    image_ts=$(date -d "$image_created" +%s 2>/dev/null || echo 0)

    if [ "$df_ts" -gt "$image_ts" ]; then
        return 0
    fi

    echo "[build-all] Skipping ${image} (up-to-date)"
    return 1
}

run_step() {
    local label="$1"
    shift
    echo "======================================================================="
    echo "[build-all] $label"
    echo "======================================================================="
    "$@"
    echo ""
}

build_dev() {
    local image="gofr-iq-dev:latest"
    local dockerfile="$SCRIPT_DIR/Dockerfile.dev"
    if should_build "$image" "$dockerfile"; then
        run_step "Building ${image}" "$SCRIPT_DIR/build-dev.sh"
    fi
}

build_prod_stack() {
    ensure_common_base
    run_step "Tagging gofr-iq-base" "$SCRIPT_DIR/build-base.sh"
    local chroma_image="gofr-iq-chromadb:latest"
    local neo4j_image="gofr-iq-neo4j:latest"
    local prod_image="gofr-iq-prod:latest"

    if should_build "$chroma_image" "$SCRIPT_DIR/Dockerfile.chromadb"; then
        run_step "Building ${chroma_image}" "$SCRIPT_DIR/build-chromadb.sh"
    fi

    if should_build "$neo4j_image" "$SCRIPT_DIR/Dockerfile.neo4j"; then
        run_step "Building ${neo4j_image}" "$SCRIPT_DIR/build-neo4j.sh"
    fi

    # Vault is built in gofr-common and shared across all projects
    # No local vault build needed

    if should_build "$prod_image" "$SCRIPT_DIR/Dockerfile.prod"; then
        run_step "Building ${prod_image}" "$SCRIPT_DIR/build-prod.sh"
    fi
}

ensure_common_base() {
    local common_base_script="${PROJECT_ROOT}/lib/gofr-common/docker/build-base.sh"
    local base_image="gofr-base:latest"

    if docker image inspect "$base_image" >/dev/null 2>&1; then
        return
    fi

    if [ ! -x "$common_base_script" ]; then
        echo "[build-all][ERROR] Missing or non-executable gofr-common base builder: $common_base_script"
        exit 1
    fi

    run_step "Building gofr-base (common)" "$common_base_script"
}

if $DEV; then
    build_dev
fi

if $PROD; then
    build_prod_stack
fi

echo "All requested builds completed."