#!/usr/bin/env bash
# Render the skills from skills-lock.json and copy them into TARGET.
# TARGET defaults to $HOME (global install); pass a project root to
# equip that project. Skills land in <TARGET>/.agents/skills and are
# mirrored to <TARGET>/.claude/skills. A project install links every skill
# the global install in $HOME already holds to that copy instead.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
TARGET="${TARGET:-${HOME}}"

log() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }

if ! command -v npx &>/dev/null; then
	warn "skills: npx not found — install Node.js first: https://nodejs.org"
	exit 1
fi

if [[ ! -d "${TARGET}" ]]; then
	warn "skills: TARGET does not exist: ${TARGET}"
	exit 2
fi

cd "${REPO_ROOT}"
src="${REPO_ROOT}/.agents/skills"
rm -rf "${src}"
log "skills: restoring from skills-lock.json..."
npx --yes skills experimental_install

if [[ ! -d "${src}" ]]; then
	warn "skills: ${src} not found after install."
	exit 1
fi

if [[ -d "${REPO_ROOT}/skills" ]]; then
	log "skills: adding first-party skills from skills/..."
	cp -a "${REPO_ROOT}/skills/." "${src}/"
fi

for root in .agents/skills .claude/skills; do
	dst="${TARGET}/${root}"
	log "skills: copying -> ${dst}"
	mkdir -p "${dst}"
	find -H "${dst}" -mindepth 1 -delete
	cp -a "${src}/." "${dst}/"
	find -H "${dst}" \( -name __pycache__ -o -name '*.py[co]' \) -prune -exec rm -rf {} +
	if [[ ! "${TARGET}" -ef "${HOME}" ]]; then
		log "skills: linking in ${dst} what ${HOME}/${root} already holds"
		for skill in "${dst}"/*; do
			global="${HOME}/${root}/${skill##*/}"
			if [[ -e "${global}" ]]; then
				rm -rf "${skill}"
				ln -s "${global}" "${skill}"
			fi
		done
	fi
done

settings="${TARGET}/.claude/settings.local.json"
if command -v node &>/dev/null; then
	log "skills: auto-enabling caveman + ponytail plugins in ${settings}"
	node "${REPO_ROOT}/scripts/enable-plugins.js" "${settings}"
else
	warn "skills: node not found; skipped auto-enabling caveman/ponytail plugins."
fi

if [[ "${TARGET}" == "${HOME}" ]]; then
	if command -v systemctl &>/dev/null && systemctl --user show-environment &>/dev/null; then
		log "skills: enabling the daily kvb-dream notification timer"
		units="${HOME}/.config/systemd/user"
		mkdir -p "${units}"
		cp -f "${REPO_ROOT}/skills/kvb-dream/systemd/kvb-dream-notify.service" "${REPO_ROOT}/skills/kvb-dream/systemd/kvb-dream-notify.timer" "${units}/"
		systemctl --user daemon-reload
		systemctl --user enable --now kvb-dream-notify.timer
	else
		warn "skills: no systemd user session; skipped the kvb-dream notification timer."
	fi
	if command -v docker &>/dev/null; then
		bash "${REPO_ROOT}/scripts/orchestrator.sh" install
		bash "${REPO_ROOT}/scripts/orchestrator.sh" runner || true
	else
		warn "skills: docker not found; skipped the Agent Orchestrator."
	fi
	log "skills: installing or updating the codebase-memory-mcp code graph for every detected agent"
	if ! curl -fsSL --proto '=https' https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.sh | bash; then
		warn "skills: the codebase-memory-mcp installer failed; the code graph keeps its previous setup."
	fi
	if (ulimit -c 0; codebase-memory-mcp config set auto_index true); then
		log "skills: auto-indexing every repository a session opens into the code graph"
	else
		warn "skills: codebase-memory-mcp is not runnable from PATH; the code graph stays off (see kvb-agent-optimize)."
	fi
	if command -v medusa &>/dev/null; then
		log "skills: the MEDUSA security scanner is installed"
	elif ! command -v pipx &>/dev/null; then
		warn "skills: pipx not found; install the MEDUSA scanner with 'pip install --user medusa-security'. Until then kvb-check-security reviews by hand."
	elif pipx install medusa-security; then
		log "skills: installed the MEDUSA security scanner for kvb-check-security"
	else
		warn "skills: the MEDUSA install failed; kvb-check-security reviews by hand."
	fi
	lizard_pin="lizard==1.24.1"
	if command -v lizard &>/dev/null; then
		log "skills: lizard is installed"
	elif ! command -v pipx &>/dev/null; then
		warn "skills: pipx not found; install lizard with 'pipx install ${lizard_pin}'. Until then principles.py skips its complexity hits."
	elif pipx install "${lizard_pin}"; then
		log "skills: installed ${lizard_pin} for the principles.py complexity hits"
	else
		warn "skills: the lizard install failed; principles.py skips its complexity hits."
	fi
	jscpd_pin="jscpd@5.4.2"
	if command -v jscpd &>/dev/null; then
		log "skills: jscpd is installed"
	elif ! command -v npm &>/dev/null; then
		warn "skills: npm not found; install jscpd with 'npm install --global --prefix ~/.local ${jscpd_pin}'. Until then principles.py skips its clone hits."
	elif npm install --global --prefix "${HOME}/.local" "${jscpd_pin}"; then
		log "skills: installed ${jscpd_pin} into ~/.local/bin for the principles.py clone hits"
	else
		warn "skills: the jscpd install failed; principles.py skips its clone hits."
	fi
fi

log "skills: done. Restart your agent to load the skills."
