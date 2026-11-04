#!/usr/bin/env bash
# Render the skills from skills-lock.json and copy them into TARGET.
# TARGET defaults to $HOME (global install); pass a project root to
# equip that project. Skills land in <TARGET>/.agents/skills and are
# mirrored to <TARGET>/.claude/skills.
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

for dst in "${TARGET}/.agents/skills" "${TARGET}/.claude/skills"; do
	log "skills: copying -> ${dst}"
	rm -rf "${dst}"
	mkdir -p "${dst}"
	cp -a "${src}/." "${dst}/"
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
	log "skills: installing or updating the codebase-memory-mcp code graph for every detected agent"
	if ! curl -fsSL --proto '=https' https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.sh | bash; then
		warn "skills: the codebase-memory-mcp installer failed; the code graph keeps its previous setup."
	fi
	if (ulimit -c 0; codebase-memory-mcp config set auto_index true); then
		log "skills: auto-indexing every repository a session opens into the code graph"
	else
		warn "skills: codebase-memory-mcp is not runnable from PATH; the code graph stays off (see kvb-agent-optimize)."
	fi
fi

log "skills: done. Restart your agent to load the skills."
