---
name: kvb-agent-optimize
description: >
  Make a repository easy for agents: a code graph index (codebase-memory-mcp)
  and lean agent instructions; kvb-optimize runs it.
---

An agent that queries a graph reads a fraction of what an agent exploring
file by file reads, and short, current, consistent instructions get followed.
This skill sets up the general code index,
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) (MIT,
fully local), and tightens the agent instructions of every repository in
scope: the current one, or those `kvb-optimize` hands over.

## Step 1: inventory

`${CLAUDE_SKILL_DIR}/scripts/agents.py --repo <dir>` prints one line per
check: AGENTS.md, any runtime-specific instruction file beside it, dead
relative links in it, whether it names the index, whether the index binary is
installed, whether the daemon's `auto_index` is off, and the state of the shared snapshot
`.codebase-memory/graph.db.zst`.

## Step 2: index

- **Binary missing**: the skills repository's `make install` runs the
  upstream installer, which installs the checksum-verified release (static
  on Linux) into `~/.local/bin` and wires the graph into every agent it
  detects (Claude Code, Codex, Gemini, Hermes, OpenClaw and more); rerunning
  it updates. It writes the agents' configuration, so it is the operator's
  step: hand `make install` to the `kvb-org-operator` skill and continue
  after the restart.

- **Index**: the skills repository's `make install` turns the daemon's
  `auto_index` off, because it would index a session root with no queue and
  no memory gate. The `scripts/graph.py hook` PreToolUse hook indexes
  instead: every git root a tool call touches, the session root included
  (additional working directories, worktrees, submodules), once it has no
  graph. It indexes nothing until `~/.config/kvb-code-graph/config.json`
  sets `queue_file_threshold` and `queue_task` (no defaults; the operator
  sets both, the hook says so once per session). A root with more files
  than the threshold (tracked plus untracked, not ignored), with a
  `.gitmodules` file or a nested repository, or whose count git cannot give
  within 2 s is enqueued once through `kvb-org-queue` under `queue_task`,
  never started by the hook; a smaller one starts a detached helper
  (`index_repository`, `async: true`, mode `full`) only while no other
  helper runs and `kvb-org-organize` reports the memory stage ok. Git runs
  with repository hooks and fsmonitor off. A failed or refused index is
  retried after 6 hours at the earliest. `make install` also enables
  `kvb-code-graph.service`, which keeps a permanent daemon so each watch
  outlives the last session; while the unit is inactive, the hook prints
  the enable command once per session and records it once as a
  `kvb-org-operator` row.
  Every skill that explores code asks the graph first. Check a root with
  `index_status` and `check_index_coverage`; every file kind it leaves out
  is a finding. Inside the sandbox read `auto_index` through `agents.py`
  (read-only `_config.db`), never `codebase-memory-mcp config get`.
- **Snapshot**: ask whether the repository shares its graph. Shared: run
  `index_repository` with `persistence: true` and commit
  `.codebase-memory/graph.db.zst` at a fixed cadence (every commit of it adds
  a full blob; Git LFS avoids that). Not shared: add `.codebase-memory/` to
  `.gitignore`, and every agent indexes on its own.
- **Domain graphs** the generic index cannot see, such as dependencies a
  project declares in its own metadata, belong to the line that owns the
  repository: record them as its task in the `kvb-org-rasci` register, never
  build them here.

## Step 3: instructions

- AGENTS.md is the only instruction file: fold any `CLAUDE.md`,
  `.claude/CLAUDE.md`, `CLAUDE.local.md` or `GEMINI.md` into it and remove
  them. Claude Code reads AGENTS.md natively (v2.1.277+) but skips it while a
  `CLAUDE.md` is on the path; Gemini CLI reads it once `context.fileName`
  lists it.
- AGENTS.md sends code questions to the graph first (`search_graph`,
  `trace_path`, `get_architecture`) and to grep only after it.
- `/claude-api prompt-audit` over AGENTS.md and the files it references finds
  stale, duplicate and contradicting rules; the dead links of step 1 join its
  findings.

## Step 4: confirm

One `AskUserQuestion` per improvement, `multiSelect: false`: the change, its
evidence, and `Apply now`, `Record as a task`, `Skip`. No repository file
changes before the answer, and nothing is committed.

## Output

| Repository | Check | Before | After | Action |
