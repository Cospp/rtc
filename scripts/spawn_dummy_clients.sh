#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COUNT="${1:-2}"
PYTHON_BIN="${PYTHON_BIN:-python}"

if ! [[ "${COUNT}" =~ ^[0-9]+$ ]] || (( COUNT <= 0 )); then
  echo "Usage: ./scripts/spawn_dummy_clients.sh <count> <file>" >&2
  echo "Example: ./scripts/spawn_dummy_clients.sh 4 C:/Users/cosku/Desktop/cb.mp4" >&2
  exit 1
fi

if (( $# < 2 )); then
  echo "Usage: ./scripts/spawn_dummy_clients.sh <count> <file>" >&2
  echo "Example: ./scripts/spawn_dummy_clients.sh 4 C:/Users/cosku/Desktop/cb.mp4" >&2
  exit 1
fi

shift || true

echo "Starting ${COUNT} dummy clients..."

pids=()
failures=0

for (( index=1; index<=COUNT; index++ )); do
  echo "[client-${index}] starting"
  "${PYTHON_BIN}" "${SCRIPT_DIR}/dummy_rtc_client.py" "$@" &
  pids+=("$!")
done

for pid in "${pids[@]}"; do
  if ! wait "${pid}"; then
    failures=$((failures + 1))
  fi
done

successes=$((COUNT - failures))
echo "Finished: ${successes} successful, ${failures} failed."

if (( failures > 0 )); then
  exit 1
fi
