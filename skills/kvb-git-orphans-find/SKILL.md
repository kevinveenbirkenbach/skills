---
name: kvb-git-orphans-find
description: >
  Find merged and abandoned branches and worktrees, propose deleting them.
---

Finds merged branches and worktrees and those with open changes nobody works
on any more, then proposes a step for each. The script only reads; nothing
goes without the operator's pick in this run.

## When

On "verwaiste branches", "alte worktrees", "was kann weg"; from step 8 of
`kvb-dream`; from `kvb-cleanup` with `--sizes` when disk runs short.

## Step 1: find

Per repository in scope:

1. Fetch first: `git fetch --no-auto-maintenance origin`, never a plain
   fetch (the `kvb-git-branch-gc` reason) and no `--prune`, which deletes
   refs.
2. `python3 ${CLAUDE_SKILL_DIR}/scripts/orphans.py --repo <dir> --default
   <branch> --stale-days 7 --top 5 --full /tmp/orphans-<repo>-<N>.md`:
   `--default` the branch `origin/HEAD` names, another limit only on the
   operator's word. `--sizes` adds and orders by each orphan's worktree size;
   it walks every file, so only when disk matters. `--json` lists every row.

The summary counts each class and shows its top rows, oldest or largest
first; the `--full` file holds all.

Merged means the tip is on `origin/<default>`, or `git cherry` finds every
commit's patch there. That catches squash and rebase merges only partly: a
squash of several commits, a rebase that changed a patch or a merge commit
on the branch stays unmerged. Say so above the summaries.

| Class | Means | Proposal |
| --- | --- | --- |
| `merged-clean` | merged, nothing dirty | `kvb-git-branch-gc` |
| `merged-dirty` | merged, dirty files | `ask` |
| `stale-open` | unmerged, dirty or unpushed (no upstream counts), idle beyond the limit, no live claim, not busy | `ask` |
| `active` | anything else; always the main worktree, the default branch and `archive/` branches | `keep` |

A merged row with a live claim or a busy process proposes `keep (claimed)`
or `keep (busy)`: never offer it. Busy is unknown without the agents-council
config, and a sandbox hides other PID namespaces: say so.

## Step 2: propose

Print each repository's summary, then:

- **merged-clean**: the rows go to the `kvb-git-branch-gc` skill; its dry
  run, claims step and pick decide. A row its dry run does not list stays.
- **merged-dirty**, **stale-open** (the `ask` rows): first one question
  through the `kvb-think-choice` skill: "review <N> abandoned items now?".
  No ends here. Yes: rounds of at most four rows in summary order, taken
  from the `--full` file, one question per row naming what a delete loses
  (dirty files, unpushed commits):
  - `archive` (recommended, loses nothing): the owner commits or stashes
    the changes, then `git branch -m <branch> archive/<branch>` and `git
    worktree remove <path>` once clean. Owner gone: an `operator.py`
    `decision` row for the changes.
  - `keep`: nothing changes.
  - `delete`: the worktree and the branch go.

## Step 3: act

Only on the operator's pick for that row, never widened:

- An agent never runs `git branch -D`, `git worktree remove --force` or
  anything outside the sandbox. Each such command becomes its own
  `operator.py add` row (`kvb-org-operator`): `--dir <repo>`, the command,
  the reason, `--check absent:<worktree path>` for a worktree, and for a
  branch `absent:<git common dir>/refs/heads/<branch>` while that loose ref
  file exists, else `manual`. The worktree row comes first: git refuses to
  delete a checked-out branch.
- Never delete a peer's worktree without the operator's pick; afterwards
  `radio.py post --to <peer>` (`kvb-org-radio`) names what went.

## Step 4: report

Per repository: rows handed to gc, archived, kept and deleted, each with its
reason, then the `operator.py run` block.

## Rules

- A pick from an earlier run does not carry over.
- Never route around a refusal through another command or a peer.
