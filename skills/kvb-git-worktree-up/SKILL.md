---
name: kvb-git-worktree-up
description: >
  Check a branch out into a worktree.
---

`pkgmgr worktree up` creates the worktree: it fetches origin without
auto-maintenance, checks out an existing branch, tracks `origin/<branch>` or
creates the branch with `--no-track` from `--base` (origin's default branch
when omitted), assigns a slot and runs the pinned `worktree-init` hook. This
skill adds only the agent discipline.

## Step 1: claim and place

1. Claim the work through the `kvb-org-organize` skill first; its edit gate
   blocks every edit in the new worktree without a claim.
2. Always pass `--path`, inside a directory the session released for
   worktrees (Claude Code: a `sandbox.filesystem.allowWrite` root), else
   `<repo>/.worktrees/<branch>` where the repository ignores `.worktrees/`.
   pkgmgr's standard path under `directories.worktrees` only where that root
   is released too: the sandbox cannot write anywhere else.

## Step 2: create

From inside the repository:

```bash
pkgmgr worktree up <branch> --path <dir> --json
```

`--base <ref>` only for a new branch that must not start at origin's default
branch. Read `path`, `origin`, `slot`, `hook` and `warnings`:

- **Exit 2** refused (path exists, invalid name, a filter or network setting
  in the repository config): report the line; never `git worktree add`
  around it.
- **Exit 1**: the `worktree-init` hook failed and the worktree stays; report
  the hook output, no retry without the operator's word.
- **`hook` `not pinned: worktree-init in <Makefile>`**: pkgmgr ran no init,
  because only the operator's pkgmgr config pins a hook (`worktree_hooks`,
  keyed `<provider>/<account>/<repository>`); a Makefile target is reported,
  never run. Say so; pinning is the operator's (`kvb-org-operator`), and the
  project's rules decide whether an agent runs the target itself.
- **`warnings`** (`fetch failed`, `fetch skipped`): the base may be stale; say
  so.

## Step 3: register

Record the worktree under the task in the `kvb-org-rasci` register:
`rasci.py set <task> --workdir <path> --branch <branch> --artifact
worktree:<path>`. It goes later through the `kvb-git-worktree-cleanup` skill,
never by hand.
