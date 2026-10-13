---
name: cleanup
description: >
  Free the disk space agents filled: ask every other agent session on this
  machine which data it still needs, inventory /tmp, Docker and the other
  directories agents write to, then propose a cleanup with its risks and let
  the operator choose through single-select (radio button) and multi-select
  (checklist) questions before anything is deleted. Trigger on /cleanup,
  "aufräumen", "bereinigen", "platte voll", "no space left on device", or when
  the operator asks to clean up after agents. Portable across projects.
---

Nothing is deleted before the operator has picked it. Every candidate carries
its owner, its size, and its risk.

## Step 1: ask the peers

List every agent the host can message (in Claude Code: `ListAgents`). Only
peers sharing this machine's filesystem and Docker daemon count: local
sessions and your own subagents. Cloud sessions and remote sessions on other
machines hold nothing here; skip them.

Send each local peer one message (`SendMessage`) and go on with step 2 while
they answer:

```text
Cleanup planned by <own session name>. Reply to me with everything you still
need, one item per line:
- paths under /tmp, caches, worktrees
- containers, compose or stack projects, volumes, images, networks
- running jobs (deploys, tests, builds) and when they finish
Reply "nothing" if you need none of it. Items you do not answer for stay.
```

## Step 2: inventory

Read-only, in parallel, sizes included:

- **Scope**: the directories agents may write to, taken from the host's
  sandbox or permission config (in Claude Code:
  `sandbox.filesystem.allowWrite` in `.claude/settings.json`) plus the session
  scratch dirs. Anything outside is out of scope, even when readable.
- **/tmp**: `du -sh` per top-level entry the current user owns. System entries
  (`.X11-unix`, `.ICE-unix`, `systemd-private-*`, `ssh-*`, `tmux-*`, sockets)
  are never candidates.
- **Docker**: `docker system df -v`; containers with state and compose project
  label, volumes with the containers using them
  (`docker ps -a --filter volume=<name>`), dangling and unused images, build
  cache, unused networks.
- **Other agent dirs**: package and tool caches (pip, npm, pre-commit, act,
  gh, buildx), worktrees with `git status --short` and whether their branch is
  merged or pushed, Ansible and build temp dirs.
- **Live use**: open handles (`fuser`, `lsof`) and running processes by name
  only (`ps -o pid,etime,comm`). Never print full command lines or
  environments: process arguments carry credentials.
- **Archive duties**: memory and project instructions that require copying
  something out before deletion (logs, reports, generated maps). Such an item
  is `archive first`, never a plain delete.

Prefer the project's own cleanup and teardown targets (Makefile, scripts) over
raw commands where they exist, and obey project rules that forbid raw
commands.

## Step 3: attribute

Give every candidate an owner: a peer's reply, a session id in the path, a
worktree or compose project name, a container label, an open handle, or
`unknown`. Then apply, first match wins:

1. Claimed by a peer: `keep`.
2. Attributable to a peer that has not answered: `keep (no answer from
   <peer>)`. Silence is not consent.
3. Archive duty: `archive first`.
4. Everything else is a candidate with a risk class:

| Risk | Meaning | Typical items |
| ---- | ------- | ------------- |
| low | regenerated automatically, cheap | stopped containers, dangling images, unused networks, scratch dirs and logs of finished sessions |
| medium | regenerated, but slow, rate-limited or network-bound | unused tagged images (re-pull, registry limits), build cache (cold rebuilds), package caches |
| high | data loss or a broken run possible | volumes, running unclaimed containers or stacks, worktrees with uncommitted or unpushed work, unread reports, anything `unknown` |

## Step 4: propose

One table, biggest first:

| Area | Item | Size | Owner | Risk | Proposal | What breaks if wrong |

Below it: reclaimable size per risk class, and every `keep` row grouped by
reason, so the operator sees what was protected and why.

Then ask with `AskUserQuestion`, at most four questions per call:

1. **Strategy** (`multiSelect: false`, radio buttons): `Conservative: low risk
   only (Recommended)`, `Standard: low and medium`, `Custom: only what I tick
   below`, `Abort`. Each description states the size it frees and its worst
   case.
2. **/tmp** (`multiSelect: true`, checklist): the candidate groups, size and
   risk in each description.
3. **Docker** (`multiSelect: true`): containers, images, build cache,
   networks, volumes.
4. **Other dirs** (`multiSelect: true`): caches, worktrees, temp dirs.

An area with more than four options is grouped by owner or risk, or asked in a
second call. A high-risk item is deleted only when it is ticked explicitly;
the strategy radio button alone never selects one. A checklist answer that
contradicts the strategy wins, since it is the more specific choice.

## Step 5: execute

- Re-check claims, open handles and running state right before each delete: a
  peer may have started something since the inventory.
- Delete exactly the selected items, by name or path. No blanket prune
  (`docker system prune -a --volumes`, `rm -rf /tmp/*`) that sweeps beyond the
  selection.
- Running stacks go down through the project's teardown target, never by
  removing their containers or volumes underneath them.
- Archive-first items: copy out, verify the copy, then delete.
- A delete failing on permissions (files owned by a container UID): use the
  project's container helper. Never sudo, never bypass the sandbox; without a
  helper, report the path.
- Stop on the first unexpected error and report it.

## Step 6: report

`df -h` and `docker system df` before and after, freed size per area, every
skipped or failed item with its reason. Tell each peer that answered which of
the removed items lay near its own.

## Rules

- Questions, inventory and proposal change nothing. Deletion needs the
  operator's selection in this run; a selection from an earlier run does not
  carry over.
- Never delete outside the agent write scope, another user's files, or system
  entries in `/tmp`.
- Never invent a peer's answer or a size. Unmeasured is `unknown`, and
  `unknown` is high risk.
