---
name: kvb-cleanup
description: >
  Free disk space agents filled in /tmp, Docker and agent dirs; delete only
  operator picks. Trigger on "aufräumen", "bereinigen",
  "platte voll", "no space left on device".
---

Delete only what the operator picked in this run; questions, inventory and
proposal change nothing. Never invent a size or a peer's answer: unmeasured
is `unknown`.

## Step 0: the chair

Shared resources belong to the `kvb-org-organize` chair; its resource watch
runs the configured low-risk cleanup. Another session chairs: send it the
request and stop, or, when the operator ordered the cleanup here, first
`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post --to <chair>
"<plan>"`.

## Step 1: inventory

Read-only, in parallel, with sizes, only in the agent write scope (Claude
Code: `sandbox.filesystem.allowWrite`) and session scratch dirs; never
another user's files. Prefer the project's cleanup and teardown targets; obey
rules forbidding raw commands.

- **/tmp**: `pkgmgr gc --report --docker --root /tmp --root <write dir>`,
  else `du -sh` per own entry; system entries (`.X11-unix`, `.ICE-unix`, `systemd-private-*`,
  `ssh-*`, `tmux-*`, sockets) are never candidates.
- **Docker**, **worktrees**: read `docker.md` (its `⚠ Volumes` checklist
  joins Step 4) and `worktrees.md` next to this file when present.
- **Agent dirs**: pip, npm, pre-commit, act, gh, buildx caches; Ansible and
  build temp dirs.
- **Register**: `council.py list --long`; `rasci.py artifacts` (`kvb-org-artefacts`,
  `--ended` for candidates).
- **Live use**: `fuser`, `lsof`, `ps -o pid,etime,comm`, never full command
  lines or environments (credentials). Sandboxed, an empty result proves
  nothing.
- **Archive duties**: memory or project rules requiring a copy before
  deletion (logs, reports, generated maps).

## Step 2: ask the owners

Owner: register worker, session id in the path, worktree or compose project,
container label, open handle, else `unknown`. `radio.py send call --to
<peer>` the text in `ask.md` next to this file once to each local peer
owning candidates the register does not cover; go on meanwhile.

## Step 3: classify

First match wins: claimed by a peer, `keep`; in a register task not `done`,
`stopped` or `stale`, `keep (task <task>)` (an ended task's items are its
worker's candidates); a running deploy, gate, test, swarm run or build, `keep
(running)`; a silent peer's, `keep (no answer from <peer>)`, silence is not
consent; sandboxed, anything touched within 24 hours, `keep (recent,
possibly in use)`; archive duty,
`archive first`, never a plain delete. Else a candidate:

- **low**, regenerated cheaply: stopped containers without volumes, dangling
  images, unused networks, finished sessions' scratch and logs.
- **medium**, regenerated slowly, rate-limited or networked: unused tagged
  images, build cache, package caches, clean worktrees already merged.
- **high**, data loss or a broken run: volumes, stopped containers with
  volumes, running unclaimed containers or stacks, dirty or unpushed
  worktrees, unread reports, anything `unknown`.

## Step 4: propose

One table, biggest first: area, item, size, owner, risk, proposal, what
breaks if wrong. Below it reclaimable size per risk and every `keep` grouped
by reason. Then `AskUserQuestion`:

1. `multiSelect: true`, at most four questions: `/tmp`, `Docker`, `Other
   dirs`, `High risk` (every high-risk candidate); size, risk and worst case
   in each option's description. Over four options: group by owner or risk,
   or call again. Only ticks select; nothing preselected.
2. `multiSelect: false`: `Execute: <n> items, <size> (Recommended)` naming
   the ticked items' worst case, `Revise the selection` (repeats 1), `Abort`.

## Step 5: execute

After `Execute`, read `execute.md` next to this file first.

## Step 6: report

`df -h` and `docker system df` before and after, freed size per area, every
skipped or failed item with its reason. `radio.py post --to <peer>` tells each
answering peer which removed items lay near its own.
