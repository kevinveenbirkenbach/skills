#!/usr/bin/env bash
# Usage: hub.sh install | check | pin <blob> | runner | hook
#   install  copy hub/ to ~/.local/share/kvb-hub, write its .env, build and
#            start the container, register the MCP server for Claude Code
#   check    image imports, container, logs, HTTP, pinned keys, hook, runner,
#            disk; exit 1 when a check fails
#   pin      pin the credential blob the hub's "Passkey registrieren" shows
#   runner   install, enable and restart the runner user service
#   hook     register the PermissionRequest hook in ~/.claude/settings.json,
#            replacing an earlier kvb-hub entry, keeping everything else and the
#            file mode, after a copy to settings.json.before-kvb-hub-hook
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
HUB="${HOME}/.local/share/kvb-hub"
STATE="${HOME}/.local/state/kvb-hub"
APPROVALS="${HOME}/.local/state/kvb-hub-approvals"
APPROVERS="${HOME}/.config/kvb-hub"
UNITS="${HOME}/.config/systemd/user"
# council.py ROOT: every agent must agree on this directory
COUNCIL="${AGENTS_COUNCIL_ROOT:-/tmp/agents-council}"
SETTINGS="${HOME}/.claude/settings.json"
LOCAL_SETTINGS="${HOME}/.claude/settings.local.json"
HOOK_TIMEOUT=110
RUNNER="kvb-hub-runner.service"
IMAGE="kvb-hub:local"
FLOOR_GB=15
FAILED=0

log() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
ok() { printf 'ok    %s\n' "$*"; }
todo() { printf 'todo  %s\n' "$*"; }
fail() {
	printf 'FAIL  %s\n' "$*"
	FAILED=1
}

port_of() {
	sed -n 's/^KVB_HUB_PORT=//p' "$1"
}

install_hub() {
	command -v docker &>/dev/null || {
		warn "skills: docker not found; skipped the kvb-hub review hub."
		return 0
	}
	local port
	port="$(port_of "${REPO_ROOT}/hub/.env")"
	log "skills: starting the kvb-hub review hub on http://localhost:${port}/"
	rm -rf "${HUB}"
	mkdir -p "${HUB}" "${STATE}" "${APPROVALS}" "${COUNCIL}" "${HOME}/.claude/projects" "${HOME}/Repositories" "${HOME}/.local/share/worktrees" "${UNITS}" "${APPROVERS}"
	chmod 700 "${APPROVERS}"
	cp -a "${REPO_ROOT}/hub/." "${HUB}/"
	chmod +x "${HUB}/client/permission_hook.py" "${HUB}/client/runner.py" "${HUB}/client/approval.py"
	log "skills: the kvb-hub PermissionRequest hook client is ${HUB}/client/permission_hook.py"
	log "skills: approvals need a pinned passkey: hub settings, 'Passkey registrieren', then 'make hub-pin CREDENTIAL=<blob>'; until then every executor refuses"
	printf 'KVB_HUB_USER=%s:%s\nKVB_HUB_STATE=%s\nKVB_HUB_COUNCIL=%s\nKVB_HUB_SKILLS=%s\nKVB_HUB_PROJECTS=%s\nKVB_HUB_REPOS=%s\nKVB_HUB_WORKTREES=%s\nKVB_HUB_TIMERS=%s\nKVB_HUB_APPROVERS=%s\n' \
		"$(id -u)" "$(id -g)" "${STATE}" "${COUNCIL}" "${HOME}/.claude/skills" "${HOME}/.claude/projects" "${HOME}/Repositories" "${HOME}/.local/share/worktrees" "${UNITS}" "${APPROVERS}" >>"${HUB}/.env"
	if ! docker compose --file "${HUB}/compose.yml" up -d --build; then
		warn "skills: docker compose failed; the kvb-hub stays down until 'make hub-install' succeeds."
	fi
	if ! command -v claude &>/dev/null; then
		warn "skills: claude not found; skipped registering the kvb-hub MCP server."
		return 0
	fi
	claude mcp remove --scope user kvb-hub &>/dev/null || true
	if claude mcp add --transport http --scope user kvb-hub "http://127.0.0.1:${port}/mcp"; then
		log "skills: registered the kvb-hub MCP server for Claude Code at user scope"
	else
		warn "skills: registering the kvb-hub MCP server for Claude Code failed."
	fi
}

runner() {
	if ! systemctl --user show-environment &>/dev/null; then
		warn "skills: no systemd user session; the kvb-hub runner is off and approved operator commands wait."
		return 1
	fi
	cp -f "${HUB}/systemd/${RUNNER}" "${UNITS}/"
	systemctl --user daemon-reload
	systemctl --user enable "${RUNNER}"
	systemctl --user restart "${RUNNER}"
	log "skills: the kvb-hub runner service runs the operator commands approved in the hub ($(systemctl --user is-active "${RUNNER}"))"
}

check_keys() {
	local file="${APPROVERS}/approvers.json"
	if [[ ! -f "${file}" ]]; then
		todo "no pinned passkey: hub settings, 'Passkey registrieren', then make hub-pin CREDENTIAL=<blob>"
		return 0
	fi
	local modes
	modes="$(stat -c '%a' "${APPROVERS}" "${file}" | paste -sd ' ')"
	if [[ "${modes}" == "700 600" ]]; then
		ok "pinned keys $(python3 -c 'import json,sys; print([c["alg"] for c in json.load(open(sys.argv[1]))["credentials"]])' "${file}") (modes ${modes})"
	else
		fail "pinned key modes are ${modes}, expected 700 600"
	fi
}

check() {
	local port code free
	port="$(port_of "${HUB}/.env")"
	if docker run --rm "${IMAGE}" --help >/dev/null; then ok "image ${IMAGE} imports every module"; else fail "image ${IMAGE} does not start"; fi
	if docker compose --file "${HUB}/compose.yml" ps --status running --services | grep -qx hub; then ok "container running"; else fail "container not running"; fi
	if docker compose --file "${HUB}/compose.yml" logs --tail 200 2>&1 | grep -q Traceback; then
		fail "traceback in the hub log:"
		docker compose --file "${HUB}/compose.yml" logs --tail 30
	else
		ok "no traceback in the last 200 log lines"
	fi
	code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/" || true)"
	if [[ "${code}" == "200" ]]; then ok "http://localhost:${port}/ answers 200"; else fail "http://localhost:${port}/ answers ${code}"; fi
	check_keys
	if grep -qs 'kvb-hub/client/permission_hook.py' "${SETTINGS}" "${LOCAL_SETTINGS}"; then
		ok "PermissionRequest hook registered"
	else
		todo "PermissionRequest hook missing: make hub-hook"
	fi
	if [[ "$(systemctl --user is-active "${RUNNER}" 2>/dev/null || true)" == "active" ]]; then
		ok "runner active; last lines:"
		journalctl --user -u "${RUNNER}" -n 10 --no-pager
	else
		todo "runner off: make hub-runner"
	fi
	free="$(df --output=avail -BG / | tail -1 | tr -dc '0-9')"
	if ((free >= FLOOR_GB)); then ok "/ has ${free} GB free"; else fail "/ has ${free} GB free, floor ${FLOOR_GB} GB"; fi
	return "${FAILED}"
}

pin() {
	[[ -n "${1:-}" ]] || {
		warn "usage: make hub-pin CREDENTIAL=<blob from 'Passkey registrieren'>"
		exit 2
	}
	python3 "${HUB}/client/approval.py" pin --port "$(port_of "${HUB}/.env")" --approvers "${APPROVERS}/approvers.json" --credential "$1"
	check_keys
	return "${FAILED}"
}

hook() {
	local command
	command="python3 \"${HUB}/client/permission_hook.py\" --port $(port_of "${HUB}/.env") --timeout ${HOOK_TIMEOUT} --approvers \"${APPROVERS}/approvers.json\" --replay \"${APPROVALS}/hook.json\""
	[[ -f "${SETTINGS}" ]] && cp -p "${SETTINGS}" "${SETTINGS}.before-kvb-hub-hook"
	python3 - "${SETTINGS}" "${command}" "$((HOOK_TIMEOUT + 10))" <<'PY'
import json, os, sys
from pathlib import Path

path, command, timeout = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
entries = settings.setdefault("hooks", {}).setdefault("PermissionRequest", [])
entries[:] = [entry for entry in entries if not any("kvb-hub/client/permission_hook.py" in hook.get("command", "") for hook in entry.get("hooks", []))]
entries.append({"matcher": "Bash", "hooks": [{"type": "command", "command": command, "timeout": timeout}]})
temporary = path.with_name(f"{path.name}.{os.getpid()}")
temporary.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
temporary.chmod(mode)
temporary.replace(path)
PY
	log "skills: registered the kvb-hub PermissionRequest hook in ${SETTINGS} (copy before: ${SETTINGS}.before-kvb-hub-hook); restart Claude Code to load it"
}

case "${1:-}" in
install) install_hub ;;
check) check ;;
pin) pin "${2:-}" ;;
runner) runner ;;
hook) hook ;;
*)
	warn "usage: hub.sh install | check | pin <blob> | runner | hook"
	exit 2
	;;
esac
