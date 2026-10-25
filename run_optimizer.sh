#!/usr/bin/env bash
set -euo pipefail

# ===== OPTIMIZER CONFIGURATION =====
OPTIMIZATION_MODE="max-crafts" # balanced retains launch/fuel/completion priorities
TARGET="metronome-4" # Any craftable material ID, e.g. ankh-4, metronome-4
DAYS=30
FUEL=500
FUEL_MODE="default" # default: existing 5T allocation budget; existing_inventory: fixed Virtue stock
# Fixed-inventory quantities are eggs (plain numbers), B or T; unlisted fuels are zero.
# Example: INITIAL_FUEL=("curiosity=120T" "kindness=80T" "resilience=250B" "integrity=50T" "humility=100T")
INITIAL_FUEL=()
PARALLEL=3
# Maximum launches PER SHIP SLOT within any rolling 60-minute window; 0 is unlimited
MAX_LAUNCHES_PER_HOUR=2
MAX_TOTAL_LAUNCHES=360 # All slots combined; 0 is unlimited
MAX_LAUNCHES_PER_DAY=0 # Per planning day across all slots; 0 is unlimited
EVENTS=1
EVENT_HOURS=48
EVENT_MULTIPLIER=2
FUEL_STEP=5
SLEEP_WINDOWS=("00:00-11:00")
NO_LAUNCH_WINDOWS=()
INVENTORY_FILE="data/inventory.csv" # Empty string disables inventory
OUTPUT_DIR="results" # Base directory; selected target is appended
SOLVER_SECONDS=200
POLISH_SECONDS=60 # Additional wall-clock budget for launch effort, fuel and schedule quality
VERBOSE_SOLVER=false # Enable HiGHS progress output
OPEN_DASHBOARD=true # Set true to open on macOS after success
# ===== END CONFIGURATION =====

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
if [[ -x .venv/bin/python ]]; then
  PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "Python 3 is required. Create .venv or install python3." >&2
  exit 127
fi

# Find the effective target before choosing the default output directory.
# Leave validation and missing-argument errors to argparse.
EFFECTIVE_TARGET="$TARGET"
EFFECTIVE_FUEL_MODE="$FUEL_MODE"
OVERRIDES=("$@")
for ((i=0; i<${#OVERRIDES[@]}; i++)); do
  case "${OVERRIDES[$i]}" in
    --target) if ((i+1<${#OVERRIDES[@]})); then EFFECTIVE_TARGET="${OVERRIDES[$((i+1))]}"; fi ;;
    --target=*) EFFECTIVE_TARGET="${OVERRIDES[$i]#--target=}" ;;
    --fuel-mode) if ((i+1<${#OVERRIDES[@]})); then EFFECTIVE_FUEL_MODE="${OVERRIDES[$((i+1))]}"; fi ;;
    --fuel-mode=*) EFFECTIVE_FUEL_MODE="${OVERRIDES[$i]#--fuel-mode=}" ;;
  esac
done
ARGS=(--mode "$OPTIMIZATION_MODE" --target "$TARGET" --days "$DAYS" --fuel "$FUEL" --fuel-mode "$FUEL_MODE" --parallel "$PARALLEL"
      --events "$EVENTS" --event-hours "$EVENT_HOURS" --event-multiplier "$EVENT_MULTIPLIER"
      --max-launches-per-hour "$MAX_LAUNCHES_PER_HOUR" --max-total-launches "$MAX_TOTAL_LAUNCHES" --max-launches-per-day "$MAX_LAUNCHES_PER_DAY" --fuel-step "$FUEL_STEP" --output-dir "$OUTPUT_DIR/$EFFECTIVE_TARGET"
      --solver-seconds "$SOLVER_SECONDS" --polish-seconds "$POLISH_SECONDS")
if [[ -n "$INVENTORY_FILE" ]]; then ARGS+=(--inventory "$INVENTORY_FILE"); fi
# An explicit CLI quantity replaces that fuel's configured stock, never adds to
# it. Keep validation/duplicate CLI errors in Python, including spelling aliases.
fuel_key() {
  local key="${1%%=*}"
  key="$(printf '%s' "$key" | tr '[:upper:]' '[:lower:]')"
  case "$key" in curiousity) key=curiosity ;; resilence) key=resilience ;; esac
  printf '%s' "$key"
}
if [[ "$EFFECTIVE_FUEL_MODE" == existing_inventory ]]; then
  for quantity in ${INITIAL_FUEL[@]+"${INITIAL_FUEL[@]}"}; do
    REPLACED=false
    for ((i=0; i<${#OVERRIDES[@]}; i++)); do
      CLI_QUANTITY=""
      case "${OVERRIDES[$i]}" in
        --initial-fuel) if ((i+1<${#OVERRIDES[@]})); then CLI_QUANTITY="${OVERRIDES[$((i+1))]}"; fi ;;
        --initial-fuel=*) CLI_QUANTITY="${OVERRIDES[$i]#--initial-fuel=}" ;;
      esac
      if [[ -n "$CLI_QUANTITY" && "$(fuel_key "$CLI_QUANTITY")" == "$(fuel_key "$quantity")" ]]; then REPLACED=true; fi
    done
    if [[ "$REPLACED" == false ]]; then ARGS+=(--initial-fuel "$quantity"); fi
  done
fi
# Bash 3.2 with nounset requires the guarded expansion for empty arrays.
for window in ${SLEEP_WINDOWS[@]+"${SLEEP_WINDOWS[@]}"}; do ARGS+=(--sleep "$window"); done
for window in ${NO_LAUNCH_WINDOWS[@]+"${NO_LAUNCH_WINDOWS[@]}"}; do ARGS+=(--no-launch "$window"); done

if [[ "$VERBOSE_SOLVER" == true ]]; then ARGS+=(--verbose-solver); fi

# Repeated scalar options use argparse's last-value-wins behavior. Window
# overrides are additive, matching the optimizer's repeatable arguments.
"$PYTHON" "$SCRIPT_DIR/optimize_reggference.py" "${ARGS[@]}" "$@"

if [[ "$OPEN_DASHBOARD" == true && "$(uname -s)" == Darwin ]]; then
  DASHBOARD_DIR="$OUTPUT_DIR/$EFFECTIVE_TARGET"
  for ((i=0; i<${#OVERRIDES[@]}; i++)); do
    case "${OVERRIDES[$i]}" in
      --output-dir) if ((i+1<${#OVERRIDES[@]})); then DASHBOARD_DIR="${OVERRIDES[$((i+1))]}"; fi ;;
      --output-dir=*) DASHBOARD_DIR="${OVERRIDES[$i]#--output-dir=}" ;;
    esac
  done
  open "$DASHBOARD_DIR/plan.html"
fi
