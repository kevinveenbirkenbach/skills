#!/usr/bin/env bash
# Param: $1 plugins-lock.json, holding tokeneconomizer.source, .commit and .patch (relative to the lock).
# Param: $2 the clone directory; created at the pin, or moved to it while clean apart from the patch.
set -euo pipefail

lock=$1
clone=$2
PROTECT="AskUserQuestion,Artifact,Skill,Agent,ToolSearch,mcp__kvb-orchestrator__*,mcp__codebase-memory-mcp__*,mcp__plugin_codebase-memory_*"

log() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }

if ! command -v git &>/dev/null || ! command -v python3 &>/dev/null; then
	warn "skills: git or python3 not found; skipped TokenEconomizer."
	exit 0
fi
{ read -r source; read -r commit; read -r patch; } < <(python3 -I -c 'import json, os, sys; entry = json.load(open(sys.argv[1]))["tokeneconomizer"]; print(entry["source"], entry["commit"], os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), entry["patch"]), sep="\n")' "${lock}")

if [[ ! -e "${clone}" ]]; then
	mkdir -p "$(dirname -- "${clone}")"
	git clone --quiet "${source}" "${clone}"
fi
reversed=0
if [[ -n "$(git -C "${clone}" status --porcelain)" ]] && git -C "${clone}" apply --reverse --check "${patch}" 2>/dev/null; then
	git -C "${clone}" apply --reverse "${patch}"
	reversed=1
fi
if [[ -n "$(git -C "${clone}" status --porcelain)" ]]; then
	if ((reversed)); then
		git -C "${clone}" apply "${patch}"
	fi
	warn "skills: ${clone} has local changes; TokenEconomizer stays off its pin ${commit}."
	exit 1
fi
if [[ "$(git -C "${clone}" rev-parse HEAD)" != "${commit}" ]]; then
	git -C "${clone}" cat-file -e "${commit}^{commit}" 2>/dev/null || git -C "${clone}" fetch --quiet origin "${commit}"
	git -C "${clone}" -c advice.detachedHead=false checkout --quiet --detach "${commit}"
fi
git -C "${clone}" apply "${patch}"
log "skills: TokenEconomizer at ${commit} with the local security patch ${patch##*/} in ${clone}"

if command -v claude &>/dev/null; then
	claude plugin install tokeneconomizer --marketplace "${clone}" --scope user
else
	log "skills: claude not found; TokenEconomizer skipped for Claude Code."
fi
if command -v codex &>/dev/null; then
	listed="$(codex plugin marketplace list 2>/dev/null || true)"
	if [[ "${listed}" != *"${clone}"* ]]; then
		codex plugin marketplace add "${clone}"
	fi
	codex plugin add tokeneconomizer@tokeneconomizer
	log "skills: TokenEconomizer for Codex takes effect once its hooks are approved: start codex, run /hooks, choose Trust all."
else
	log "skills: codex not found; TokenEconomizer skipped for Codex."
fi
"${clone}/plugin/scripts/te" config set toolprune=propose microskills=envfacts "toolprune_protect=${PROTECT}" --global
log "skills: TokenEconomizer settings: tool pruning only proposes, micro-skills from repeated failures, loop guard on"
