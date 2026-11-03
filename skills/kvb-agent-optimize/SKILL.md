---
name: kvb-agent-optimize
description: >
  Make a repository easy for agents: a code graph index (codebase-memory-mcp)
  and lean agent instructions. Trigger on /kvb-agent-optimize; kvb-optimize
  runs it.
---

An agent that queries a graph reads a fraction of what an agent exploring
file by file reads, and short, current, consistent instructions get followed.
This skill sets up the general code index,
[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) (MIT,
fully local), and tightens the agent instructions of every repository in
scope: the current one, or those `kvb-optimize` hands over.

## Step 1: inventory

`${CLAUDE_SKILL_DIR}/scripts/agents.py --repo <dir>` prints one line per
check: AGENTS.md, whether CLAUDE.md and GEMINI.md point to it, dead relative
links in it, whether it names the index, whether the index binary is
installed, and the state of the shared snapshot
`.codebase-memory/graph.db.zst`.

## Step 2: index

- **Binary missing**: installing registers an MCP server in the agent
  configuration, so it is the operator's step; hand these to the
  `kvb-org-operator` skill and continue after the restart:

  ```bash
  yay -S codebase-memory-mcp-bin
  claude plugin marketplace add DeusData/codebase-memory-mcp
  claude plugin install codebase-memory@codebase-memory
  ```

- **Index**: once installed, the skills repository's `make install` switches
  `auto_index` on, so every repository a session opens is indexed and
  watched; every skill that explores code asks the graph first. Check it with
  `index_status`, index by hand with `index_repository` only where it is
  missing, then `check_index_coverage`; every file kind it leaves out is a
  finding.
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

- AGENTS.md is the single source; CLAUDE.md and GEMINI.md only point to it
  (`@AGENTS.md`).
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
