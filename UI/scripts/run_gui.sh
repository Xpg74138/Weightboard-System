#!/usr/bin/env bash
# Usage: bash scripts/run_gui.sh [--demo | /dev/ttyUSB0 [9600]]
set -e
cd "$(dirname "$0")/.."
if [ -n "${SENSOR_HUB_PYTHON:-}" ]; then
  task_python="$SENSOR_HUB_PYTHON"
elif [ -x .venv/bin/python ]; then
  task_python="$(pwd)/.venv/bin/python"
else
  task_python="${PYTHON:-python3}"
fi
if ! "$task_python" -c "import PyQt5, serial" 2>/dev/null; then
  echo "Missing dependencies. Run: $task_python -m pip install -r requirements.txt"
  exit 2
fi
if [ $# -eq 0 ]; then
  exec "$task_python" -B -m sensor_hub
elif [[ "$1" == -* ]]; then
  exec "$task_python" -B -m sensor_hub "$@"
elif [ $# -eq 1 ]; then
  exec "$task_python" -B -m sensor_hub --port "$1"
else
  exec "$task_python" -B -m sensor_hub --port "$1" --baud "$2"
fi
