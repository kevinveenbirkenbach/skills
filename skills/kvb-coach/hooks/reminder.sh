#!/usr/bin/env bash
set -euo pipefail

hours="${COACH_STAMP_DIR:-${HOME}/.claude/.coach-hours}"
hour="${COACH_HOUR:-$(date +%Y-%m-%dT%H)}"

mkdir -p "${hours}"
mkdir "${hours}/${hour}" 2>/dev/null || exit 0
find "${hours}" -mindepth 1 -maxdepth 1 -type d ! -name "${hour}" -exec rmdir {} +

cat <<'HINT'
COACH HOUR: a new full hour began. Before answering the operator's request,
run the kvb-coach skill in its short form: at most three lines, the most
urgent area first, then continue with the request.
HINT
