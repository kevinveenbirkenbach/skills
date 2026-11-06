#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/bin:/bin

interval="${DREAM_INTERVAL_SECONDS:-43200}"
stamps="${DREAM_STAMP_DIR:-${HOME}/.claude/.dream-stamps}"

session="$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("session_id", ""))' 2>/dev/null)" || exit 0
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
DREAM HINT: over twelve hours since this agent's last hint. Show the operator
this notice verbatim as a short block, then continue with their request. Do NOT
run kvb-dream, do not start replaying the history, do not ask questions about
it.

    💤 /kvb-dream - process the last 24h of every repository and session this
       agent touched: memory, improvements, kvb-optimize and the cleanups.
       Runs only when you trigger it.
HINT
