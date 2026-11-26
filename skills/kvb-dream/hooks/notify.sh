#!/usr/bin/env bash
set -euo pipefail

[[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]] || exit 0
command -v notify-send >/dev/null || exit 0

schedules="$(dirname "$0")/../../kvb-org-organize/scripts/schedules.py"
[[ -f "$schedules" ]] && command -v python3 >/dev/null || exit 0
python3 -I "$schedules" check dream-popup >/dev/null 2>&1 || exit 0

popups="$(dirname "$0")/../../kvb-org-organize/scripts/popups.py"
muted=3
status=0
if [[ -f "$popups" ]] && command -v python3 >/dev/null; then
	python3 -I "$popups" allowed dream >/dev/null 2>&1 || status=$?
fi
[[ "$status" -ne "$muted" ]] || exit 0

notify-send --app-name=kvb-dream "kvb-dream" \
	"Time to dream: run /kvb-dream in your agent sessions to process the day."
