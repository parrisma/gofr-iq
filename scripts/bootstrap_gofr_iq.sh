#!/bin/bash
# =============================================================================
# gofr-iq bootstrap helper
# =============================================================================
# Idempotent: checks state before acting and provides guided prompts.
#
# This script will:
#   - Initialize git submodules (if needed)
#   - Run gofr-common platform bootstrap
#   - Verify Vault is healthy
#   - Build gofr-iq dev and prod images (if missing)
#   - Provision AppRole creds and seed secrets volume (if needed)
#
# Requirements:
#   - Docker Engine + Docker Compose plugin
#   - Git (for submodules)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ASSUME_YES=false
START_DEV=false
START_PROD=false
RUN_TESTS=false
TRACE=false
LOG_FILE=""
SCRIPT_START_TS=""
NO_LOG=false
STEP=0

usage() {
  cat << 'EOF'
GOFR-IQ Bootstrap

Usage:
  ./scripts/bootstrap_gofr_iq.sh [--yes] [--trace] [--log-file PATH] [--no-log]
                               [--start-dev] [--start-prod] [--run-tests] [--auto-dev-tests]

Options:
  --yes, -y    Run non-interactively and auto-accept prompts
  --trace      Enable bash xtrace for detailed logs
  --log-file   Write logs to a specific file path
  --no-log     Disable file logging (stdout/stderr only)
  --start-dev  Start the dev container at the end
  --start-prod Start the prod stack at the end
  --run-tests  Run tests inside the dev container (requires it to be running)
  --auto-dev-tests  Equivalent to --start-dev --run-tests
  --help, -h   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      ASSUME_YES=true
      shift
      ;;
    --trace)
      TRACE=true
      shift
      ;;
    --log-file)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "Missing value for --log-file" >&2
        usage
        exit 1
      fi
      LOG_FILE="$2"
      shift 2
      ;;
    --no-log)
      NO_LOG=true
      shift
      ;;
    --start-dev)
      START_DEV=true
      shift
      ;;
    --start-prod)
      START_PROD=true
      shift
      ;;
    --run-tests)
      RUN_TESTS=true
      shift
      ;;
    --auto-dev-tests)
      START_DEV=true
      RUN_TESTS=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }
info() { echo "[$(timestamp)] [INFO] $*"; }
ok() { echo "[$(timestamp)] [OK]   $*"; }
warn() { echo "[$(timestamp)] [WARN] $*"; }
err() { echo "[$(timestamp)] [ERR]  $*" >&2; }

die() {
  err "$1"
  if [[ -n "${2:-}" ]]; then
    err "Fix: $2"
  fi
  exit 1
}

setup_logging() {
  SCRIPT_START_TS="$(date +%s)"
  if [[ "$NO_LOG" == "true" ]]; then
    LOG_FILE=""
    info "File logging disabled."
  else
    if [[ -z "$LOG_FILE" ]]; then
      LOG_FILE="${PROJECT_ROOT}/logs/bootstrap_gofr_iq_$(date +%Y%m%d_%H%M%S).log"
    fi

    local log_dir
    log_dir="$(dirname "$LOG_FILE")"
    if ! mkdir -p "$log_dir"; then
      warn "Failed to create log directory: $log_dir"
      warn "Logging will continue on stdout/stderr only."
      LOG_FILE=""
    else
      exec > >(tee -a "$LOG_FILE") 2>&1
      info "Logging to ${LOG_FILE}"
    fi
  fi

  if [[ "$TRACE" == "true" ]]; then
    export PS4='+ [$(date +%H:%M:%S)] [TRACE] '
    set -x
    info "Trace enabled."
  fi
}

on_error() {
  local exit_code=$?
  local line_no=${BASH_LINENO[0]}
  local cmd=${BASH_COMMAND}
  err "Command failed (exit ${exit_code}) at line ${line_no}: ${cmd}"
  if [[ -n "$LOG_FILE" ]]; then
    err "Fix: review ${LOG_FILE} or re-run with --trace for more details."
  else
    err "Fix: re-run with --log-file PATH or --trace for more details."
  fi
  exit "$exit_code"
}

on_exit() {
  local exit_code=$?
  if [[ -n "$SCRIPT_START_TS" ]]; then
    local end_ts
    end_ts="$(date +%s)"
    local elapsed
    elapsed=$((end_ts - SCRIPT_START_TS))
    info "Total elapsed time: ${elapsed}s"
  fi
  exit "$exit_code"
}

run_step() {
  local label="$1"
  shift
  STEP=$((STEP + 1))
  info "Step ${STEP}: ${label}"
  local step_start
  step_start="$(date +%s)"
  "$@"
  local status=$?
  local step_end
  step_end="$(date +%s)"
  info "Step ${STEP} completed in $((step_end - step_start))s (status ${status})"
  return "$status"
}

confirm() {
  local prompt="$1"
  if [[ "$ASSUME_YES" == "true" ]]; then
    info "Auto-accept: ${prompt}"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    warn "No interactive input available. Skipping: ${prompt}"
    return 1
  fi
  read -r -p "${prompt} [y/N]: " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

ensure_git_clone() {
  if [[ ! -d "${PROJECT_ROOT}/.git" ]]; then
    die "This does not look like a git clone (missing .git)." \
      "Clone the repo first, then rerun this script from the repo root."
  fi
  if ! command -v git >/dev/null 2>&1; then
    die "git is not installed or not on PATH." \
      "Install Git and ensure it is available in your PATH."
  fi
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    die "Docker is not installed or not on PATH." \
      "Install Docker Engine and ensure the 'docker' command is available."
  fi
  if ! docker info >/dev/null 2>&1; then
    die "Docker is not running or not reachable." \
      "Start Docker, ensure your user can access /var/run/docker.sock, and retry."
  fi
  if ! docker compose version >/dev/null 2>&1; then
    die "Docker Compose plugin not available." \
      "Install the Compose plugin (docker compose) and retry."
  fi
}

ensure_submodule() {
  if [[ -f "${PROJECT_ROOT}/lib/gofr-common/pyproject.toml" ]]; then
    ok "gofr-common submodule present."
    return 0
  fi

  info "gofr-common submodule not found. Initializing submodules..."
  (cd "${PROJECT_ROOT}" && git submodule update --init --recursive)

  if [[ ! -f "${PROJECT_ROOT}/lib/gofr-common/pyproject.toml" ]]; then
    die "Submodule init completed but gofr-common is still missing." \
      "Run 'git submodule update --init --recursive' manually and retry."
  fi

  ok "Submodules initialized."
}

run_platform_bootstrap() {
  local platform_script="${PROJECT_ROOT}/lib/gofr-common/scripts/bootstrap_platform.sh"
  if [[ ! -f "${platform_script}" ]]; then
    die "Platform bootstrap script not found at ${platform_script}." \
      "Re-run submodule init or check that gofr-common is present."
  fi

  info "Running GOFR platform bootstrap..."
  if [[ "$ASSUME_YES" == "true" ]]; then
    (cd "${PROJECT_ROOT}" && bash "${platform_script}" --yes)
  else
    (cd "${PROJECT_ROOT}" && bash "${platform_script}")
  fi
}

build_dev_image() {
  if docker image inspect gofr-iq-dev:latest >/dev/null 2>&1; then
    ok "Dev image exists: gofr-iq-dev:latest"
    return 0
  fi

  if [[ ! -f "${PROJECT_ROOT}/docker/build-dev.sh" ]]; then
    die "Dev build script not found at docker/build-dev.sh." \
      "Verify your clone is complete and that the docker directory exists."
  fi

  info "Dev image gofr-iq-dev:latest is missing. Building now..."
  (cd "${PROJECT_ROOT}" && bash ./docker/build-dev.sh)
  ok "Dev image built: gofr-iq-dev:latest"
}

build_prod_image() {
  if docker image inspect gofr-iq-prod:latest >/dev/null 2>&1; then
    ok "Prod image exists: gofr-iq-prod:latest"
    return 0
  fi

  if [[ ! -f "${PROJECT_ROOT}/docker/build-prod.sh" ]]; then
    die "Prod build script not found at docker/build-prod.sh." \
      "Verify your clone is complete and that the docker directory exists."
  fi

  info "Prod image gofr-iq-prod:latest is missing. Building now..."
  (cd "${PROJECT_ROOT}" && bash ./docker/build-prod.sh)
  ok "Prod image built: gofr-iq-prod:latest"
}

ensure_approle_creds() {
  if [[ ! -f "${PROJECT_ROOT}/scripts/ensure_approle.sh" ]]; then
    die "ensure_approle.sh not found at scripts/ensure_approle.sh." \
      "Sync your repository and ensure scripts/ exists."
  fi

  # Always delegate to ensure_approle.sh -- it validates existing creds
  # via live AppRole login and only re-provisions if missing or stale.
  info "Validating/provisioning AppRole creds for gofr-iq..."
  (cd "${PROJECT_ROOT}" && bash ./scripts/ensure_approle.sh)
  ok "AppRole creds validated for gofr-iq."
}

seed_secrets_volume() {
  local seed_script="${PROJECT_ROOT}/scripts/migrate_secrets_to_volume.sh"
  if [[ ! -f "${seed_script}" ]]; then
    die "Secrets seeding script not found at ${seed_script}." \
      "Add scripts/migrate_secrets_to_volume.sh and rerun."
  fi

  info "Seeding secrets into Docker volumes (gofr-secrets, gofr-secrets-test)."
  (cd "${PROJECT_ROOT}" && bash "${seed_script}")
  ok "Secrets volumes seeded."
}

ensure_vault_healthy() {
  local manage_script="${PROJECT_ROOT}/lib/gofr-common/scripts/manage_vault.sh"

  # Source port config
  local ports_env="${PROJECT_ROOT}/lib/gofr-common/config/gofr_ports.env"
  if [[ -f "$ports_env" ]]; then
    # shellcheck source=/dev/null
    source "$ports_env"
  fi
  local vault_port="${GOFR_VAULT_PORT:-8201}"
  local vault_url="http://gofr-vault:${vault_port}"

  # 1. Vault must be reachable
  local health_resp
  health_resp=$(curl -s --connect-timeout 3 --max-time 5 "${vault_url}/v1/sys/health" 2>/dev/null || true)
  if [[ -z "$health_resp" ]]; then
    warn "Vault not reachable at ${vault_url} -- attempting start..."
    if [[ -f "$manage_script" ]]; then
      bash "$manage_script" start
      sleep 3
      health_resp=$(curl -s --connect-timeout 3 --max-time 5 "${vault_url}/v1/sys/health" 2>/dev/null || true)
    fi
    if [[ -z "$health_resp" ]]; then
      die "Vault not reachable at ${vault_url}." \
        "Run: ./lib/gofr-common/scripts/manage_vault.sh start"
    fi
  fi
  ok "Vault is reachable."

  # 2. Must be unsealed
  local is_sealed
  is_sealed=$(echo "$health_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sealed', True))" 2>/dev/null || echo "True")
  if [[ "$is_sealed" != "False" ]]; then
    warn "Vault is sealed -- attempting unseal..."
    if [[ -f "$manage_script" ]]; then
      bash "$manage_script" unseal
      sleep 2
      health_resp=$(curl -s --connect-timeout 3 --max-time 5 "${vault_url}/v1/sys/health" 2>/dev/null || true)
      is_sealed=$(echo "$health_resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sealed', True))" 2>/dev/null || echo "True")
    fi
    if [[ "$is_sealed" != "False" ]]; then
      die "Vault is sealed." \
        "Run: ./lib/gofr-common/scripts/manage_vault.sh unseal"
    fi
  fi
  ok "Vault is unsealed."

  # 3. Health check via manage_vault.sh
  if [[ -f "$manage_script" ]]; then
    if ! bash "$manage_script" health; then
      warn "Vault health check reported warnings (see above); continuing."
    else
      ok "Vault health check passed."
    fi
  fi
}

start_dev_container() {
  if docker ps --format '{{.Names}}' | grep -q '^gofr-iq-dev$'; then
    ok "Dev container already running: gofr-iq-dev"
    return 0
  fi

  if [[ ! -f "${PROJECT_ROOT}/scripts/run-dev-container.sh" ]]; then
    die "Dev run script not found at scripts/run-dev-container.sh." \
      "Verify your clone is complete."
  fi

  info "Starting dev container (gofr-iq-dev)..."
  (cd "${PROJECT_ROOT}" && bash ./scripts/run-dev-container.sh)
  ok "Dev container started."
}

start_prod_stack() {
  info "Starting production stack..."
  if [[ ! -f "${PROJECT_ROOT}/docker/start-prod.sh" ]]; then
    die "Prod start script not found at docker/start-prod.sh." \
      "Verify your clone is complete."
  fi
  (cd "${PROJECT_ROOT}" && bash ./docker/start-prod.sh)
  ok "Production stack started."
}

run_tests_in_dev() {
  if ! docker ps --format '{{.Names}}' | grep -q '^gofr-iq-dev$'; then
    warn "Dev container is not running."
    if [[ "$START_DEV" == "true" ]]; then
      start_dev_container
    else
      warn "Fix: start it with --start-dev or run ./scripts/run-dev-container.sh first."
      return 1
    fi
  fi

  info "Running tests inside dev container..."
  docker exec gofr-iq-dev bash -lc "cd /home/gofr/devroot/gofr-iq && ./scripts/run_tests.sh"
  ok "Test run completed."
}

main() {
  trap on_error ERR
  trap on_exit EXIT
  setup_logging

  info "gofr-iq bootstrap"
  info "Project root: ${PROJECT_ROOT}"
  echo ""

  run_step "Validate git clone" ensure_git_clone
  run_step "Validate Docker availability" require_docker
  run_step "Ensure submodule" ensure_submodule
  run_step "Run platform bootstrap" run_platform_bootstrap

  run_step "Verify Vault is healthy" ensure_vault_healthy

  run_step "Build dev image" build_dev_image || true
  run_step "Build prod image" build_prod_image || true
  run_step "Ensure AppRole creds" ensure_approle_creds
  run_step "Seed secrets volume" seed_secrets_volume

  if [[ "$START_DEV" == "true" ]]; then
    run_step "Start dev container" start_dev_container
  fi

  if [[ "$START_PROD" == "true" ]]; then
    run_step "Start prod stack" start_prod_stack
  fi

  if [[ "$RUN_TESTS" == "true" ]]; then
    run_step "Run tests in dev container" run_tests_in_dev || true
  fi

  echo ""
  ok "gofr-iq bootstrap complete."
  info "Next: ./scripts/run-dev-container.sh or ./docker/start-prod.sh"
}

main
