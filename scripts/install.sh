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
log "skills: restoring from skills-lock.json..."
npx --yes skills experimental_install

src="${REPO_ROOT}/.agents/skills"
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

settings="${TARGET}/.claude/settings.json"
if command -v node &>/dev/null; then
	log "skills: auto-enabling caveman + ponytail plugins in ${settings}"
	node "${REPO_ROOT}/scripts/enable-plugins.js" "${settings}"
else
	warn "skills: node not found; skipped auto-enabling caveman/ponytail plugins."
fi

log "skills: done. Restart your agent to load the skills."
