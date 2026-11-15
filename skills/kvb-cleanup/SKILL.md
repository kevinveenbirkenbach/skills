---
name: kvb-cleanup
description: >
  Free disk space agents filled in /tmp, Docker and agent dirs; delete only
  operator picks. Trigger on "aufräumen", "bereinigen",
  "platte voll", "no space left on device".
---

Delete only this run's operator picks; asking, inventory and proposal change
nothing. Never invent a size or a peer's answer: unmeasured is `unknown`.

## Step 0: the chair

Shared resources belong to the `kvb-org-organize` chair; its watch
runs the configured low-risk cleanup. Another session chairs: send it the
request and stop, or, ordered here by the operator, first
`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post --to <chair>
"<plan>"`.

## Step 1: inventory

Read-only, parallel, sized, only in the agent write scope (Claude Code:
`sandbox.filesystem.allowWrite`) and session scratch dirs, never another
user's files. Prefer project cleanup and teardown targets; obey raw-command
bans.

- **/tmp**: `pkgmgr gc --report --docker --root /tmp --root <write dir>`,
  else `du -sh` per own entry; never system entries (`.*-unix`,
  `systemd-private-*`, `ssh-*`, `tmux-*`, sockets).
- **Docker**, **worktrees**: read `docker.md` (its `⚠ Volumes` checklist
  joins Step 4) and `worktrees.md` here when present.
- **Agent dirs**: pip, npm, pre-commit, act, gh, buildx caches; Ansible and
  build temp dirs.
- **Council root** (`~/.local/state/agents-shared`): `archive/` only.
- **Register**: `council.py list --long`; `rasci.py artifacts`
  (`kvb-org-artefacts`, `--ended` for candidates).
- **Queue**: `${CLAUDE_SKILL_DIR}/../kvb-org-queue-cleanup/scripts/cleanup.py
  request`; go on meanwhile.
- **Live use**: `fuser` (exit 1 or 123: free), `lsof`, `ps -o
  pid,etime,comm`; never full command lines or environments (credentials).
  Sandboxed, an empty result proves nothing.
- **Archive duties**: memory or project rules requiring a copy before
  deletion (logs, reports, generated maps).

## Step 2: ask the owners

Owner: register worker, path session id, worktree or compose project,
container label, open handle, else `unknown`. Once per local peer owning
unregistered candidates, `radio.py send call --to <peer>` the `ask.md` text;
go on meanwhile.

## Step 3: classify

First match wins: claimed by a peer, `keep`; in a register task not `done`,
`stopped` or `stale` (a branch merged into the default makes it
`stale`; an ended task's items are its worker's candidates), `keep (task <task>)`; a
running deploy, gate, test, swarm or build, `keep (running)`; a silent peer's,
`keep (no answer from <peer>)`, silence is not consent; sandboxed, touched
within 24 hours (`find -mmin -1440`; bfs fails on `-newermt`) and neither
owner-released nor operator-picked, `keep (recent, possibly in use)`; archive
duty, `archive first`, never a plain delete. Else a candidate:

- **low**, cheap to regenerate: stopped containers without volumes, dangling
  images, unused networks, ended sessions' scratch and logs.
- **medium**, slow, rate-limited or networked to regenerate: unused tagged
  images, build and package caches, clean merged worktrees.
- **high**, data loss or a broken run: volumes, stopped containers with
  volumes, running unclaimed containers or stacks, dirty or unpushed
  worktrees, unread reports, anything `unknown`.

## Step 4: propose

One table, biggest first: area, item, size, owner, risk, proposal, what
breaks if wrong. Below it reclaimable size per risk and every `keep` by
reason. Then `AskUserQuestion`:

1. `multiSelect: true`, up to four questions: `/tmp`, `Docker`, `Other
   dirs`, `High risk` (every high-risk candidate); each option names size,
   risk and worst case. Over four options, group by owner or risk or call
   again; merge single items into one question: one-option questions fail.
   Only ticks select, not an empty `Other` answer; nothing preselected.
2. `multiSelect: false`: `Execute: <n> items, <size> (Recommended)` naming
   the ticked items' worst case, `Revise the selection` (repeats 1), `Abort`.

## Step 5: execute

After `Execute`, read `execute.md` first.

## Step 6: report

`df -h` and `docker system df` before and after, freed size per area, skipped
or failed items with reasons. `radio.py post --to <peer>` each
answering peer the removed items near its own.
