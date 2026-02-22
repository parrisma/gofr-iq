#!/bin/bash
# =============================================================================
# Simulation Runner - Uses Production Environment
# =============================================================================
# Thin wrapper around simulation/run_simulation.py.
# Adds:
# - Preflight checks (uv, repo paths, docker availability)
# - Clearer warnings about output directory reuse / --regenerate behavior
# - Run logging + recovery hints for partial failures
#
# Common usage:
#   ./run_simulation.sh --count 50                    # Generate and ingest 50 new documents
#   ./run_simulation.sh --ingest-only                 # Ingest existing documents from output dir
#   ./run_simulation.sh --skip-generate               # Same as --ingest-only
#   ./run_simulation.sh --validate-only               # Setup/validation without data generation
#   ./run_simulation.sh --refresh-timestamps          # Refresh published_at in JSONs then exit
#   ./run_simulation.sh --phase3 --regenerate         # Phase3 calibration injection
#   ./run_simulation.sh --phase4 --regenerate         # Phase4 calibration injection
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PY_RUNNER="${PROJECT_ROOT}/simulation/run_simulation.py"

die() {
	echo "ERROR: $*" >&2
	exit 1
}

warn() {
	echo "WARN:  $*" >&2
}

info() {
	echo "INFO:  $*" >&2
}

have_cmd() {
	command -v "$1" >/dev/null 2>&1
}

usage_hint() {
	cat >&2 <<'EOF'
Recovery hints:
	- If generation failed part-way: rerun the same command WITHOUT --regenerate to resume using existing JSONs.
	- If ingestion failed part-way: rerun with --ingest-only (and the same --output) to retry ingestion.
	- If you want a truly clean run: delete the output directory contents before rerunning.
EOF
}

on_error() {
	local exit_code=$?
	echo "" >&2
	echo "ERROR: simulation run failed (exit=${exit_code})." >&2
	if [[ -n "${LOG_FILE:-}" && -f "${LOG_FILE:-}" ]]; then
		echo "ERROR: log saved to: ${LOG_FILE}" >&2
	fi
	usage_hint
	exit "${exit_code}"
}

trap on_error ERR

cd "${PROJECT_ROOT}"

[[ -f "${PY_RUNNER}" ]] || die "Missing ${PY_RUNNER} (are you in the gofr-iq repo?)"

have_cmd uv || die "uv not found on PATH (required)."

# Docker is required because run_simulation.py fetches secrets via docker exec into gofr-vault.
if have_cmd docker; then
	if ! docker ps >/dev/null 2>&1; then
		warn "docker is installed but not reachable (is the daemon running / are you in the dev container?)"
	fi
else
	warn "docker not found on PATH; run_simulation.py will likely fail when fetching Vault secrets"
fi

# -----------------------------------------------------------------------------
# Arg inspection (best-effort) to emit meaningful warnings before running python
# -----------------------------------------------------------------------------
phase3=0
phase4=0
regenerate=0
skip_generate=0
ingest_only=0
validate_only=0
refresh_ts=0
output_arg=""
spread_minutes=""

args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
	a="${args[$i]}"
	case "${a}" in
		--phase3) phase3=1 ;;
		--phase4) phase4=1 ;;
		--regenerate) regenerate=1 ;;
		--skip-generate) skip_generate=1 ;;
		--ingest-only) ingest_only=1 ;;
		--validate-only) validate_only=1 ;;
		--refresh-timestamps) refresh_ts=1 ;;
		--output)
			if (( i + 1 < ${#args[@]} )); then
				output_arg="${args[$((i+1))]}"
			fi
			;;
		--spread-minutes)
			if (( i + 1 < ${#args[@]} )); then
				spread_minutes="${args[$((i+1))]}"
			fi
			;;
	esac
done

if (( phase3 == 1 && phase4 == 1 )); then
	die "--phase3 and --phase4 are mutually exclusive"
fi

# Determine effective output directory (mirror python defaults).
if [[ -n "${output_arg}" ]]; then
	output_dir="${output_arg}"
else
	if (( phase3 == 1 )); then
		output_dir="simulation/test_output_phase3"
	elif (( phase4 == 1 )); then
		output_dir="simulation/test_output_phase4"
	else
		output_dir="simulation/test_output"
	fi
fi

# Normalize relative paths against PROJECT_ROOT for filesystem checks.
if [[ "${output_dir}" != /* ]]; then
	output_path="${PROJECT_ROOT}/${output_dir}"
else
	output_path="${output_dir}"
fi

existing_count=0
if [[ -d "${output_path}" ]]; then
	existing_count=$(ls -1 "${output_path}"/synthetic_*.json 2>/dev/null | wc -l | tr -d ' ' || true)
fi

if (( validate_only == 0 && refresh_ts == 0 )); then
	if (( existing_count > 0 )); then
		if (( regenerate == 1 )); then
			warn "${output_dir} already contains ${existing_count} synthetic_*.json and --regenerate is set."
			warn "This will append new files (not overwrite). For a clean run, delete the directory contents first."
		else
			info "${output_dir} already contains ${existing_count} synthetic_*.json."
			info "This is resumable/idempotent behavior: rerun without --regenerate to reuse cached files."
		fi
	fi
fi

if (( refresh_ts == 1 )); then
	info "Refreshing timestamps in ${output_dir} (and phase dirs when using default test_output)."
	if [[ -n "${spread_minutes}" ]]; then
		info "Using spread window: ${spread_minutes} minute(s)."
	fi
fi

# -----------------------------------------------------------------------------
# Run logging
# -----------------------------------------------------------------------------
LOG_DIR="${PROJECT_ROOT}/simulation/run_logs"
mkdir -p "${LOG_DIR}"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/run_${RUN_ID}.log"

info "Command: uv run python ${PY_RUNNER} ${*}" 
info "Output:  ${output_dir}"
info "Log:     ${LOG_FILE}"

# Default: tee output to log for post-mortem. Opt out via GOFR_SIM_NO_TEE=1.
if [[ "${GOFR_SIM_NO_TEE:-}" == "1" ]]; then
	uv run python "${PY_RUNNER}" "$@"
else
	uv run python "${PY_RUNNER}" "$@" 2>&1 | tee "${LOG_FILE}"
fi

# If we got here, success.
trap - ERR
