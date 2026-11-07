# Agent Instructions

## Platform-agnostic development

Everything in this repository MUST work on every agent runtime, not only on
the one developing it: Claude Code, Codex, Gemini CLI, Hermes, OpenClaw and
any other that reads skills. The same holds for operating systems and
distributions.

- **Logic in scripts**: behaviour lives in `python3` or `bash` scripts that
  any runtime can call. Hooks, plugins and settings of one runtime are thin
  adapters over those scripts, never the only path to a feature.
- **Skills stay portable**: a `SKILL.md` that uses a runtime-specific tool
  (`AskUserQuestion`, `SendMessage`, a slash command) says what the step
  needs, so another runtime can use its own equivalent.
- **Installs reach every runtime**: install into the cross-runtime locations
  (`~/.agents/skills`) or through an installer that configures every
  detected agent; runtime-specific locations are mirrors. Of a tool that
  ships both, take the agent-agnostic integration over one runtime's plugin,
  and never both: the same server would run twice.
- **No single package manager**: an install never depends on one OS or
  distribution's package manager; prefer upstream or statically linked
  release builds.
- **One instruction file**: rules live here and nowhere else; no
  `CLAUDE.md`, `CLAUDE.local.md` or `GEMINI.md`. Claude Code reads this file
  natively from v2.1.277; Gemini CLI once its `context.fileName` setting
  lists `AGENTS.md`.

## Scope against package-manager

Deterministic logic an operator could run without an agent (branches,
worktrees, cleanups, releases) lives in
[package-manager](https://github.com/kevinveenbirkenbach/package-manager) as
a `pkgmgr` command with its tests, never as a script in a skill. A skill
wrapping it holds only the agent discipline: claims, picks, handover.

## Code questions

Ask the codebase-memory-mcp graph first (`search_graph`, `trace_path`,
`get_architecture`); grep only after it.
