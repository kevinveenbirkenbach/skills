#!/usr/bin/env bash
set -euo pipefail

interval="${DREAM_INTERVAL_SECONDS:-43200}"
if [[ -n "${DREAM_STAMP:-}" ]]; then
	stamp="${DREAM_STAMP}"
else
	git_dir="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
	stamp="${git_dir}/.dream-stamp"
fi

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
DREAM HINT: over twelve hours since the last hint for this repository. Show the
operator this notice verbatim as a short block, then continue with their
request. Do NOT run kvb-skill-dream, do not start replaying the history, do
not ask questions about it.

    💤 /kvb-skill-dream - consolidate the last 24h in this repository: what
       held, what broke, which hypotheses follow, into memory and improvement
       proposals.
       Runs only when you trigger it.
HINT
