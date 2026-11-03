#!/usr/bin/env bash
set -euo pipefail

interval="${AUTOTUNE_INTERVAL_SECONDS:-3600}"
stamp="${AUTOTUNE_STAMP:-${HOME}/.claude/.autotune-stamp}"

now="$(date +%s)"
last=0
if [[ -f "${stamp}" ]]; then
	read -r last <"${stamp}" || true
	[[ "${last}" =~ ^[0-9]+$ ]] || last=0
fi

if ((now - last < interval)); then
	exit 0
fi

mkdir -p "$(dirname "${stamp}")"
printf '%s\n' "${now}" >"${stamp}"

cat <<'HINT'
AUTOTUNE HINT: over an hour since the last hint. Show the operator this notice
verbatim as a short block, then continue with their request. Do NOT run
kvb-skill-tune, do not propose skills, do not ask questions about it.

    💡 /kvb-skill-tune - generate a new skill or optimize an existing one
       (fewer tokens, fewer errors, more focus, learnings that persist).
       Runs only when you trigger it.
HINT
