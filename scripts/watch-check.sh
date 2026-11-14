#!/usr/bin/env bash
# Usage: watch-check.sh
#   Shows whether the agents-council watch hook is stuck: running hook
#   processes, holders of the kept queue history, and the age of the stored
#   resource stage. Exit 1 when the stored stage is older than STALE_SECONDS.
set -euo pipefail

COUNCIL_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/skills/kvb-org-organize/scripts/councilroot.py"
STATE="$(python3 "${COUNCIL_ROOT}" root)/watch.json"
KEPT="$(python3 "${COUNCIL_ROOT}" durable)/queue-history.jsonl"
STALE_SECONDS=600

printf 'watch hooks running: %s\n' "$(pgrep -fc 'watch.py watch' || true)"
if command -v lsof &>/dev/null; then
	printf 'holders of %s:\n' "${KEPT}"
	lsof "${KEPT}" 2>/dev/null || printf '  none\n'
else
	printf 'lsof not installed; holders of %s unknown\n' "${KEPT}"
fi
python3 -c '
import json, sys, time
state = json.load(open(sys.argv[1]))
stage, free, age = state["stage"], state["free"], round(time.time() - state["checked"])
print(f"stored stage {stage}, {free:.1f} GB free, {age} s old")
sys.exit(1 if age > int(sys.argv[2]) else 0)
' "${STATE}" "${STALE_SECONDS}"
