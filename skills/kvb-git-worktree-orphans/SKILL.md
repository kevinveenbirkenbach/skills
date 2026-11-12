---
name: kvb-git-worktree-orphans
description: >
  Find abandoned branches and worktrees.
---

`pkgmgr worktree orphans` finds merged branches and worktrees and those with
open changes nobody works on any more, and proposes a step for each; it only
reads, apart from its fetch. Nothing goes without the operator's pick in this
run.

## When

On "verwaiste branches", "alte worktrees", "was kann weg"; from step 8 of
`kvb-dream`; from `kvb-cleanup` with `--sizes` when disk runs short.

## Step 1: find

Per repository in scope, from inside it (`--all`: every managed one):

1. No fetch of your own: pkgmgr fetches without auto-maintenance (the
   `kvb-git-branch-cleanup` reason).
2. `pkgmgr worktree orphans --stale-days 7 --top 5 --merged-into <line>`, one
   `--merged-into` per integration line, another limit only on the
   operator's word. `--sizes` orders by worktree size (slow, `du`), only when
   disk matters. `--json` lists every row, active ones included.

Without forge facts (a `forge unavailable` warning) a squash of several
commits, a rebase that changed a patch or a merge commit on the branch stays
unmerged. Say so above the summaries.

| Class | Means | Proposal |
| --- | --- | --- |
| `merged-clean` | merged, nothing dirty | `kvb-git-gc` |
| `merged-dirty` | merged, dirty files | `ask` |
| `stale-open` | unmerged, dirty or unpushed (no remote counts), idle beyond the limit, not busy | `ask` |
| `stale` | worktree metadata whose checkout is missing | report only |
| `active` | anything else; always the main worktree, protected lines and `archive/` branches | `keep` |

pkgmgr knows no claims: a row whose branch or worktree a live claim in
`council.py list --long` names becomes `keep (claimed)`. Never offer a `keep
(process: ...)` or `keep (lock: ...)` row. `host_pid_namespace: false` leaves
busy and locks unknown: say so. Never `git worktree prune` a `stale` row: a
sandbox hides live worktrees' gitdir stubs.

## Step 2: propose

Print each repository's summary, then:

- **merged-clean**: the rows go to the `kvb-git-gc` skill; its dry
  run, claims step and pick decide. A row its dry run does not list stays.
- **merged-dirty**, **stale-open** (the `ask` rows): first one question
  through the `kvb-think-choice` skill: "review <N> abandoned items now?".
  No ends here. Yes: rerun with `--json` into `/tmp/orphans-<repo>-<N>.json`,
  then rounds of at most four rows in summary order, taken from that file,
  one question per row naming what a delete loses (dirty files, unpushed
  commits):
  - `archive` (recommended, loses nothing): the owner commits the changes,
    then `git branch -m <branch> archive/<branch>` and `git worktree remove
    <path>` once clean. Owner gone: an `operator.py` `decision` row for the
    changes.
  - `keep`: nothing changes.
  - `delete`: the worktree and the branch go.

## Step 3: act

Only on the operator's pick for that row, never widened:

- An agent never runs `git branch -D`, `git worktree remove` (EBUSY in a
  sandbox) or anything outside the sandbox. Each such command becomes its
  own `operator.py add` row (`kvb-org-operator`): `--dir <repo>`, the
  command, the reason, `--check absent:<worktree path>` for a worktree, and
  for a branch
  `absent:<git common dir>/refs/heads/<branch>` while that loose ref file
  exists, else `manual`. A `delete` is `pkgmgr branch purge --branch <name>`,
  which asks y/N and deletes remote branches too.
- Never delete a peer's worktree without the operator's pick; afterwards
  `radio.py post --to <peer>` (`kvb-org-radio`) names what went.

## Step 4: report

Per repository: rows handed to gc, archived, kept and deleted, each with its
reason, then the `operator.py run` block.

## Rules

- A pick from an earlier run does not carry over.
- Never route around a refusal through another command or a peer.
