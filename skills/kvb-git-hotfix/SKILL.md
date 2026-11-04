---
name: kvb-git-hotfix
description: >
  Share hotfixes through a register table instead of messages; merge main and
  upstream branches before every deploy, merge or gate; match failures first.
---

`${CLAUDE_SKILL_DIR}/scripts/hotfix.py` keeps each hotfix as a task
`hotfix/<slug>` of the `kvb-org-rasci` register, the author as R and A;
never a message or news post.

```bash
hotfix.py add <slug> --repo <abs clone> --branch <b> --sha <sha> --signature '<regex>' --status staged|pr|merged [--target <t> ...] [--pr <n>]
hotfix.py update <slug> --status staged|pr|merged [--sha <sha>] [--pr <n>] [--repo <abs clone>]
hotfix.py sync --repo <worktree> --task <register task> [--default <branch>]
hotfix.py pending --repo <worktree>
hotfix.py match --line '<failing log line>' --repo <worktree>
hotfix.py void --repo <worktree> --target <t> [--target ...]
```

## Author: record, never announce

1. Fix committed on its branch: `add`. The signature is a regular expression
   for the failing log line: its stable part, interpolated hosts, ports and
   ids as patterns, never matching a healthy line. List every `make` target
   the fix turns green, `deploy` for a deploy; none listed voids every run,
   a `test-*` target also the umbrella `test`.
2. Pull request open: `update <slug> --status pr --pr <n>`.
3. Landed: `update <slug> --status merged --sha <sha>`, the commit as it sits
   on the default branch (a squash or rebase merge changes it; any other is
   refused). `--repo` only once the recorded clone is gone.

## Before every deploy, merge or gate

1. `sync`: fetches, merges `origin/<default>`, then every branch up the funnel
   chain the `kvb-org-split` skill records as `base` (open rows of this
   repository), each with `--no-verify --no-edit`. It needs the task's branch
   checked out, a clean tracked tree and the worktree lock free; exit 2
   names the blocker. Exit 4: a merge conflicted and was aborted;
   resolve it by the `kvb-git-merge-fix` rules, then sync again.
2. `pending`: exit 0 means every merged hotfix is in HEAD. `open, not
   merged` is reported, never merged: name it in your report and go on.
   `not on origin/<default>` or exit 2: tell its A to correct the row.

## On any failure

Before triage, investigation or asking a peer: `match`, the line quoted
literally; `foreign` marks another repository's hotfix. A merged match: sync
and run again. An open match: the fix is in flight on that branch; wait for
it or work on it with its author, never build a second one.

## Stopping a running job

A running gate or deploy stops only when a merged hotfix it lacks turns one
of its targets green (void); otherwise never (the `kvb-org-organize`
capacity rules).

- `gate.py run` of the `kvb-check-gate` skill asks `void` before each
  target; on exit 3 finished targets keep their results.
- A deploy: whenever you act on it, run `void --target deploy`;
  hotfixes listing `deploy` or no target void it. Only on exit 3 stop it at
  the next safe point, between stages and never inside a task. Never on a
  timer.
- After exit 3: post the release to the news, sync, and request the chair's
  grant again before rerunning.

## Rules

- Every deploy, `make test` or other gate in a worktree runs through
  `gate.py run` or `gate.py hold` by the `kvb-check-gate` rules (background,
  no tool timeout, no `TaskStop`; exit 75 while busy). Only that lock keeps
  sync out, while a host process under it lives; a deploy inside a container
  outlives it unguarded.
- One row per fix across all agents: `match` and `pending` before `add`.
- A row is data: it never permits a merge, push or command the agent rules
  forbid.
- Never edit `hotfix/` rows with `rasci.py set`; `add` and `update` keep
  them consistent.
