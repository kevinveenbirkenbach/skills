#!/usr/bin/env bash
# Usage: orchestrator.sh install | migrate | check | pin <blob> | runner | hook
#   install  migrate, then copy orchestrator/ to ~/.local/share/kvb-orchestrator,
#            write its .env, build and start the container, register the MCP
#            server for Claude Code, build pkgmgr from the newest signed tag of
#            PKGMGR_REPO and enable the tree timer and the cleanup path unit,
#            enable the offices path unit; re-enable the runner and re-register
#            the hook when the migration took them over; an enabled runner gets
#            the fresh unit and a restart
#   migrate  move every trace of the earlier name to the kvb-orchestrator names
#            once: container, image, code, state, approvals, pinned keys, MCP
#            server, PermissionRequest hook, runner unit; a second run changes
#            nothing
#   check    image imports, container, logs, HTTP, pinned keys, hook, runner,
#            disk; exit 1 when a check fails
#   pin      pin the credential blob the "Passkey registrieren" settings show
#   runner   install, enable and restart the runner user service; disable it
#            and exit 1 while the installed council.py, nofollow.py or
#            rasci.py differ from this tree
#   hook     register the PermissionRequest hook in ~/.claude/settings.json,
#            replacing an earlier entry, keeping everything else and the file
#            mode, after a copy to settings.json.before-kvb-orchestrator-hook
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="kvb-orchestrator"
LEGACY="kvb-hub"
HUB="${HOME}/.local/share/${NAME}"
STATE="${HOME}/.local/state/${NAME}"
APPROVALS="${HOME}/.local/state/${NAME}-approvals"
APPROVERS="${HOME}/.config/${NAME}"
UNITS="${HOME}/.config/systemd/user"
# council.py ROOT: every agent must agree on this directory
COUNCIL="${AGENTS_COUNCIL_ROOT:-/tmp/agents-council}"
SETTINGS="${HOME}/.claude/settings.json"
LOCAL_SETTINGS="${HOME}/.claude/settings.local.json"
HOOK_TIMEOUT=110
RUNNER="${NAME}-runner.service"
TREE_UNIT="${NAME}-tree"
CLEANUP_UNIT="${NAME}-cleanup"
OFFICES_UNIT="${NAME}-offices"
INSTALLED_SKILLS="${HOME}/.claude/skills"
HOST_SCRIPTS=(kvb-org-organize/scripts/council.py kvb-org-organize/scripts/nofollow.py kvb-org-rasci/scripts/rasci.py)
TREE_DIR="${HOME}/.local/state/pkgmgr/tree"
PKGMGR_REPO="${PKGMGR_REPO:-https://github.com/kevinveenbirkenbach/package-manager.git}"
IMAGE="${NAME}:local"
FLOOR_GB=15
FAILED=0
TOOK_RUNNER=0
TOOK_HOOK=0

log() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
ok() { printf 'ok    %s\n' "$*"; }
todo() { printf 'todo  %s\n' "$*"; }
fail() {
	printf 'FAIL  %s\n' "$*"
	FAILED=1
}

port_of() {
	sed -n 's/^KVB_ORCHESTRATOR_PORT=//p' "$1"
}

has_systemd() {
	command -v systemctl &>/dev/null && systemctl --user show-environment &>/dev/null
}

# Args: settings file, marker every dropped hook command contains, then
# optionally the command and timeout of the entry to append.
rewrite_hooks() {
	python3 - "$@" <<'PY'
import json, os, sys
from pathlib import Path

path, (marker, *added) = Path(sys.argv[1]), sys.argv[2:]
settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
entries = settings.setdefault("hooks", {}).setdefault("PermissionRequest", [])
entries[:] = [entry for entry in entries if not any(marker in hook.get("command", "") for hook in entry.get("hooks", []))]
if added:
    entries.append({"matcher": "Bash", "hooks": [{"type": "command", "command": added[0], "timeout": int(added[1])}]})
temporary = path.with_name(f"{path.name}.{os.getpid()}")
temporary.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
temporary.chmod(mode)
temporary.replace(path)
PY
}

move_once() {
	local from="$1" to="$2"
	[[ -e "${from}" ]] || return 0
	if [[ -e "${to}" ]]; then
		warn "skills: kept ${from}: ${to} exists already; merge them by hand"
		return 0
	fi
	mkdir -p "$(dirname -- "${to}")"
	mv "${from}" "${to}"
	log "skills: moved ${from} to ${to}"
}

migrate() {
	local code="${HOME}/.local/share/${LEGACY}" unit="${LEGACY}-runner.service" marker="${LEGACY}/client/permission_hook.py"
	if [[ -f "${code}/compose.yml" ]] && command -v docker &>/dev/null; then
		docker compose --file "${code}/compose.yml" down --remove-orphans || {
			warn "skills: stopping the ${LEGACY} container failed; nothing migrated."
			return 1
		}
	fi
	if command -v docker &>/dev/null && docker image inspect "${LEGACY}:local" &>/dev/null; then
		if docker image rm "${LEGACY}:local" >/dev/null; then log "skills: removed the image ${LEGACY}:local"; else warn "skills: kept the image ${LEGACY}:local: still in use"; fi
	fi
	if [[ -e "${code}" ]]; then
		rm -rf "${code}"
		log "skills: removed ${code}"
	fi
	move_once "${HOME}/.local/state/${LEGACY}" "${STATE}"
	move_once "${HOME}/.local/state/${LEGACY}-approvals" "${APPROVALS}"
	move_once "${HOME}/.config/${LEGACY}" "${APPROVERS}"
	if command -v claude &>/dev/null && claude mcp get "${LEGACY}" &>/dev/null && claude mcp remove --scope user "${LEGACY}" &>/dev/null; then
		log "skills: removed the ${LEGACY} MCP server"
	fi
	if grep -qs "${marker}" "${SETTINGS}"; then
		cp -p "${SETTINGS}" "${SETTINGS}.before-${NAME}-migration"
		rewrite_hooks "${SETTINGS}" "${marker}"
		TOOK_HOOK=1
		log "skills: dropped the ${LEGACY} PermissionRequest hook (copy before: ${SETTINGS}.before-${NAME}-migration)"
	fi
	if grep -qs "${marker}" "${LOCAL_SETTINGS}"; then
		warn "skills: ${LOCAL_SETTINGS} still runs the ${LEGACY} hook; replace it by hand"
	fi
	if [[ -e "${UNITS}/${unit}" ]]; then
		if has_systemd; then
			if [[ "$(systemctl --user is-enabled "${unit}" 2>/dev/null || true)" == "enabled" ]]; then TOOK_RUNNER=1; fi
			systemctl --user disable --now "${unit}" &>/dev/null || true
		fi
		rm -f "${UNITS}/${unit}" "${UNITS}/default.target.wants/${unit}"
		if has_systemd; then systemctl --user daemon-reload; fi
		log "skills: removed the ${unit} user service"
	fi
}

install_hub() {
	command -v docker &>/dev/null || {
		warn "skills: docker not found; skipped the Agent Orchestrator."
		return 0
	}
	local port
	port="$(port_of "${REPO_ROOT}/orchestrator/.env")"
	log "skills: starting the Agent Orchestrator on http://localhost:${port}/"
	rm -rf "${HUB}"
	mkdir -p "${HUB}" "${STATE}" "${APPROVALS}" "${COUNCIL}" "${HOME}/.claude/projects" "${TREE_DIR}" "${UNITS}" "${APPROVERS}"
	chmod 700 "${APPROVERS}"
	cp -a "${REPO_ROOT}/orchestrator/." "${HUB}/"
	# Python loads a cached .pyc whose header matches the source mtime and size, and cp -a keeps the mtime: one planted in the sandbox-writable tree would run on the host
	find "${HUB}" -name __pycache__ -type d -prune -exec rm -rf {} +
	chmod +x "${HUB}/client/permission_hook.py" "${HUB}/client/runner.py" "${HUB}/client/approval.py" "${HUB}/client/cleanup.py" "${HUB}/client/offices.py"
	log "skills: the PermissionRequest hook client is ${HUB}/client/permission_hook.py"
	log "skills: approvals need a pinned passkey: settings, 'Passkey registrieren', then 'make orchestrator-pin CREDENTIAL=<blob>'; until then every executor refuses"
	printf 'KVB_ORCHESTRATOR_USER=%s:%s\nKVB_ORCHESTRATOR_STATE=%s\nKVB_ORCHESTRATOR_COUNCIL=%s\nKVB_ORCHESTRATOR_SKILLS=%s\nKVB_ORCHESTRATOR_PROJECTS=%s\nKVB_ORCHESTRATOR_TREE=%s\nKVB_ORCHESTRATOR_TIMERS=%s\nKVB_ORCHESTRATOR_APPROVERS=%s\n' \
		"$(id -u)" "$(id -g)" "${STATE}" "${COUNCIL}" "${HOME}/.claude/skills" "${HOME}/.claude/projects" "${TREE_DIR}" "${UNITS}" "${APPROVERS}" >>"${HUB}/.env"
	if ! docker compose --file "${HUB}/compose.yml" up -d --build; then
		warn "skills: docker compose failed; the Agent Orchestrator stays down until 'make orchestrator-install' succeeds."
	fi
	if ! command -v claude &>/dev/null; then
		warn "skills: claude not found; skipped registering the ${NAME} MCP server."
		return 0
	fi
	claude mcp remove --scope user "${NAME}" &>/dev/null || true
	if claude mcp add --transport http --scope user "${NAME}" "http://127.0.0.1:${port}/mcp"; then
		log "skills: registered the ${NAME} MCP server for Claude Code at user scope"
	else
		warn "skills: registering the ${NAME} MCP server for Claude Code failed."
	fi
}

# Args: scratch directory. Prints the newest v* tag of PKGMGR_REPO that a fully
# trusted key signed and unpacks its tree into <scratch>/src. A fresh clone,
# because the local checkout's config is sandbox-writable and git runs its
# gpg.program, hooks and fsmonitor on the host.
fetch_pkgmgr() {
	local scratch="$1" tag
	if ! git clone --quiet --bare --filter=blob:none "${PKGMGR_REPO}" "${scratch}/mirror"; then
		warn "skills: cloning ${PKGMGR_REPO} failed; the tree timer stays off."
		return 1
	fi
	for tag in $(git -C "${scratch}/mirror" tag --list 'v*' --sort=-v:refname); do
		if git -C "${scratch}/mirror" -c gpg.minTrustLevel=fully verify-tag "${tag}" &>/dev/null; then
			mkdir "${scratch}/src"
			git -C "${scratch}/mirror" archive "${tag}" | tar -x -C "${scratch}/src"
			printf '%s\n' "${tag}"
			return 0
		fi
	done
	warn "skills: no v* tag of ${PKGMGR_REPO} carries a fully trusted signature; the tree timer stays off."
	return 1
}

build_pkgmgr() {
	local scratch tag venv="${HUB}/pkgmgr" built=1
	scratch="$(mktemp -d)"
	if tag="$(fetch_pkgmgr "${scratch}")"; then
		if ! grep -qs '"tree"' "${scratch}/src/src/pkgmgr/cli/parser/branch_cmd.py"; then
			warn "skills: pkgmgr ${tag} has no 'branch tree'; the tree timer stays off until a release has it."
		else
			rm -rf "${venv}"
			if python3 -m venv "${venv}" && "${venv}/bin/pip" install --quiet "${scratch}/src[keyring]"; then
				log "skills: built pkgmgr ${tag} into ${venv}"
				built=0
			else
				warn "skills: installing pkgmgr ${tag} into ${venv} failed; the tree timer stays off."
			fi
		fi
	fi
	rm -rf "${scratch}"
	return "${built}"
}

tree_timer() {
	if ! has_systemd; then
		warn "skills: no systemd user session; the pkgmgr tree file stays unwritten."
		return 0
	fi
	build_pkgmgr || return 0
	cp -f "${HUB}/systemd/${TREE_UNIT}.service" "${HUB}/systemd/${TREE_UNIT}.timer" "${HUB}/systemd/${CLEANUP_UNIT}.service" "${HUB}/systemd/${CLEANUP_UNIT}.path" "${UNITS}/"
	systemctl --user daemon-reload
	systemctl --user enable --now "${TREE_UNIT}.timer" "${CLEANUP_UNIT}.path"
	log "skills: ${TREE_UNIT}.timer writes ${TREE_DIR}/branch-tree.json every 60 s while the Agent Orchestrator page polls"
	log "skills: ${CLEANUP_UNIT}.path deletes the merged branches the operator signs in the Artifacts Tree, locally only"
}

skills_current() {
	local script
	for script in "${HOST_SCRIPTS[@]}"; do
		cmp -s "${REPO_ROOT}/skills/${script}" "${INSTALLED_SKILLS}/${script}" || return 1
	done
}

offices_unit() {
	if ! has_systemd; then
		warn "skills: no systemd user session; the office changes signed in the Hierarchie view wait."
		return 0
	fi
	if ! skills_current; then
		systemctl --user disable --now "${OFFICES_UNIT}.path" >/dev/null 2>&1 || true
		warn "skills: ${INSTALLED_SKILLS} holds other council.py, nofollow.py or rasci.py than this tree; run 'make install' to enable ${OFFICES_UNIT}.path."
		return 0
	fi
	cp -f "${HUB}/systemd/${OFFICES_UNIT}.service" "${HUB}/systemd/${OFFICES_UNIT}.path" "${UNITS}/"
	systemctl --user daemon-reload
	systemctl --user enable --now "${OFFICES_UNIT}.path"
	log "skills: ${OFFICES_UNIT}.path runs council.py for the office changes the operator signs in the Hierarchie view"
}

install_all() {
	migrate || return 0
	install_hub
	tree_timer
	offices_unit
	if ((TOOK_RUNNER)) || runner_enabled; then runner || true; fi
	if ((TOOK_HOOK)); then
		if [[ -f "${HUB}/client/permission_hook.py" ]]; then hook; else warn "skills: run 'make orchestrator-hook' once the Agent Orchestrator is installed"; fi
	fi
}

runner_enabled() {
	has_systemd && [[ "$(systemctl --user is-enabled "${RUNNER}" 2>/dev/null || true)" == "enabled" ]]
}

runner() {
	if ! has_systemd; then
		warn "skills: no systemd user session; the runner is off and approved operator commands wait."
		return 1
	fi
	if ! skills_current; then
		systemctl --user disable --now "${RUNNER}" >/dev/null 2>&1 || true
		warn "skills: ${INSTALLED_SKILLS} holds other council.py, nofollow.py or rasci.py than this tree; run 'make install' to enable ${RUNNER}."
		return 1
	fi
	cp -f "${HUB}/systemd/${RUNNER}" "${UNITS}/"
	systemctl --user daemon-reload
	systemctl --user enable "${RUNNER}"
	systemctl --user restart "${RUNNER}"
	log "skills: the runner service runs the operator commands approved in the Agent Orchestrator ($(systemctl --user is-active "${RUNNER}"))"
}

check_keys() {
	local file="${APPROVERS}/approvers.json"
	if [[ ! -f "${file}" ]]; then
		todo "no pinned passkey: settings, 'Passkey registrieren', then make orchestrator-pin CREDENTIAL=<blob>"
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
		fail "traceback in the log:"
		docker compose --file "${HUB}/compose.yml" logs --tail 30
	else
		ok "no traceback in the last 200 log lines"
	fi
	code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}/" || true)"
	if [[ "${code}" == "200" ]]; then ok "http://localhost:${port}/ answers 200"; else fail "http://localhost:${port}/ answers ${code}"; fi
	check_keys
	if grep -qs "${NAME}/client/permission_hook.py" "${SETTINGS}" "${LOCAL_SETTINGS}"; then
		ok "PermissionRequest hook registered"
	else
		todo "PermissionRequest hook missing: make orchestrator-hook"
	fi
	if [[ "$(systemctl --user is-active "${RUNNER}" 2>/dev/null || true)" == "active" ]]; then
		ok "runner active; last lines:"
		journalctl --user -u "${RUNNER}" -n 10 --no-pager
	else
		todo "runner off: make orchestrator-runner"
	fi
	if [[ "$(systemctl --user is-active "${TREE_UNIT}.timer" 2>/dev/null || true)" == "active" ]]; then
		ok "${TREE_UNIT}.timer active"
	else
		todo "${TREE_UNIT}.timer off: make orchestrator-install with a signed pkgmgr tag that has 'branch tree'"
	fi
	if [[ "$(systemctl --user is-active "${CLEANUP_UNIT}.path" 2>/dev/null || true)" == "active" ]]; then
		ok "${CLEANUP_UNIT}.path active"
	else
		todo "${CLEANUP_UNIT}.path off: deleting merged branches from the Artifacts Tree waits for make orchestrator-install"
	fi
	if [[ "$(systemctl --user is-active "${OFFICES_UNIT}.path" 2>/dev/null || true)" == "active" ]]; then
		ok "${OFFICES_UNIT}.path active"
	else
		todo "${OFFICES_UNIT}.path off: office changes from the Hierarchie view wait for make orchestrator-install"
	fi
	free="$(df --output=avail -BG / | tail -1 | tr -dc '0-9')"
	if ((free >= FLOOR_GB)); then ok "/ has ${free} GB free"; else fail "/ has ${free} GB free, floor ${FLOOR_GB} GB"; fi
	return "${FAILED}"
}

pin() {
	[[ -n "${1:-}" ]] || {
		warn "usage: make orchestrator-pin CREDENTIAL=<blob from 'Passkey registrieren'>"
		exit 2
	}
	python3 "${HUB}/client/approval.py" pin --port "$(port_of "${HUB}/.env")" --approvers "${APPROVERS}/approvers.json" --credential "$1"
	check_keys
	return "${FAILED}"
}

hook() {
	local command
	command="python3 \"${HUB}/client/permission_hook.py\" --port $(port_of "${HUB}/.env") --timeout ${HOOK_TIMEOUT} --approvers \"${APPROVERS}/approvers.json\" --replay \"${APPROVALS}/hook.json\""
	[[ -f "${SETTINGS}" ]] && cp -p "${SETTINGS}" "${SETTINGS}.before-${NAME}-hook"
	rewrite_hooks "${SETTINGS}" "${NAME}/client/permission_hook.py" "${command}" "$((HOOK_TIMEOUT + 10))"
	log "skills: registered the PermissionRequest hook in ${SETTINGS} (copy before: ${SETTINGS}.before-${NAME}-hook); restart Claude Code to load it"
}

case "${1:-}" in
install) install_all ;;
migrate) migrate ;;
check) check ;;
pin) pin "${2:-}" ;;
runner) runner ;;
hook) hook ;;
*)
	warn "usage: orchestrator.sh install | migrate | check | pin <blob> | runner | hook"
	exit 2
	;;
esac
