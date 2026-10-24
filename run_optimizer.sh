#!/usr/bin/env bash
set -euo pipefail

# ===== OPTIMIZER CONFIGURATION =====
TARGET="metronome-4" # Any craftable material ID, e.g. ankh-4
DAYS=70
FUEL=500
PARALLEL=3
EVENTS=2
EVENT_HOURS=48
EVENT_MULTIPLIER=2
FUEL_STEP=5
SLEEP_WINDOWS=("00:00-11:00")
NO_LAUNCH_WINDOWS=()
INVENTORY_FILE="data/inventory.csv" # Empty string disables inventory
OUTPUT_DIR="results" # Base directory; selected target is appended
SOLVER_SECONDS=120
OPEN_DASHBOARD=false # Set true to open on macOS after success
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
OVERRIDES=("$@")
for ((i=0; i<${#OVERRIDES[@]}; i++)); do
  case "${OVERRIDES[$i]}" in
    --target) if ((i+1<${#OVERRIDES[@]})); then EFFECTIVE_TARGET="${OVERRIDES[$((i+1))]}"; fi ;;
    --target=*) EFFECTIVE_TARGET="${OVERRIDES[$i]#--target=}" ;;
  esac
done
ARGS=(--target "$TARGET" --days "$DAYS" --fuel "$FUEL" --parallel "$PARALLEL"
      --events "$EVENTS" --event-hours "$EVENT_HOURS" --event-multiplier "$EVENT_MULTIPLIER"
      --fuel-step "$FUEL_STEP" --output-dir "$OUTPUT_DIR/$EFFECTIVE_TARGET"
      --solver-seconds "$SOLVER_SECONDS")
if [[ -n "$INVENTORY_FILE" ]]; then ARGS+=(--inventory "$INVENTORY_FILE"); fi
# Bash 3.2 with nounset requires the guarded expansion for empty arrays.
for window in ${SLEEP_WINDOWS[@]+"${SLEEP_WINDOWS[@]}"}; do ARGS+=(--sleep "$window"); done
for window in ${NO_LAUNCH_WINDOWS[@]+"${NO_LAUNCH_WINDOWS[@]}"}; do ARGS+=(--no-launch "$window"); done

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
