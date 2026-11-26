#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/bin:/bin

schedules="$(dirname "$0")/../../kvb-org-organize/scripts/schedules.py"
[[ -f "${schedules}" ]] || exit 0
hours="$(/usr/bin/python3 -I "${schedules}" check dream </dev/null 2>/dev/null)" || exit 0
[[ "${hours}" =~ ^[0-9]+$ ]] || exit 0
interval="$((hours * 3600))"
stamps="${DREAM_STAMP_DIR:-${HOME}/.claude/.dream-stamps}"

session="$(/usr/bin/python3 -I -c'import json, sys; print(json.load(sys.stdin).get("session_id", ""))' 2>/dev/null)" || exit 0
[[ "${session}" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0
stamp="${stamps}/${session}"

now="$(date +%s)"
last=0
if [[ -f "${stamp}" ]]; then
	read -r last <"${stamp}" || true
	[[ "${last}" =~ ^[0-9]+$ ]] || last=0
fi

if ((now - last < interval)); then
	exit 0
fi

mkdir -p "${stamps}"
printf '%s\n' "${now}" >"${stamp}"

cat <<'HINT'
DREAM HINT: the dream reminder is on in the hub's Schedules tab. Show the operator
this notice verbatim as a short block, then continue with their request. Do NOT
run kvb-dream, do not start replaying the history, do not ask questions about
it.

    💤 /kvb-dream - process the last 24h of every repository and session this
       agent touched: memory, improvements, kvb-optimize and the cleanups.
       Runs only when you trigger it.
HINT
