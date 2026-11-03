#!/usr/bin/env bash
set -euo pipefail

[[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]] || exit 0
command -v notify-send >/dev/null || exit 0

notify-send --app-name=kvb-dream "kvb-dream" \
	"Time to dream: run /kvb-dream in your agent sessions to process the day."
