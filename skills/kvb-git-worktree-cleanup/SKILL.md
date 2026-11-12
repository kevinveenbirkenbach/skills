---
name: kvb-git-worktree-cleanup
description: >
  Remove merged or pushed clean worktrees.
---

`pkgmgr worktree cleanup` removes a clean worktree whose commits are merged
or pushed: the pinned `worktree-fini` hook, its compose stack with volumes and
images, the checkout; the branch stays. This skill adds only the agent
discipline: run the steps of the `kvb-git-branch-cleanup` skill
(`${CLAUDE_SKILL_DIR}/../kvb-git-branch-cleanup/SKILL.md`, with its
`apply.md` and `unmerged.md`) with these changes.

## Changes

- **Claim**: `work/worktree-cleanup-<repo>`, or `work/worktree-cleanup-all`.
  The apply takes stacks down with their volumes, so the chair's grant comes
  first.
- **Dry run**: `pkgmgr worktree cleanup --json --sizes --min-age 24
  --merged-into <line>`, output to `/tmp/worktree-cleanup-<N>.json`. A
  candidate may be `unmerged` with `unpushed` 0: its worktree goes, its
  branch stays; its description says so.
- **Hooks**: `hook:worktree-fini` among the `actions` means the operator's
  pkgmgr config pins it (`worktree_hooks`, keyed
  `<provider>/<account>/<repository>`). Without it pkgmgr runs no fini hook,
  even where the worktree's Makefile defines a `worktree-fini` target: name
  such a target in the item's note, since its teardown then does not run.
  Pinning is the operator's; never run the target in place of pkgmgr.
- **Apply**: `pkgmgr worktree cleanup --apply --json --branch <name or path>`,
  one `--branch` per picked item, `| tee
  /tmp/worktree-cleanup-apply-<N>.json`. From an agent sandbox it always goes
  to the operator: pkgmgr refuses there, and `git worktree remove` fails with
  EBUSY on the read-only `.git/worktrees/<id>` mount. Never remove a checkout
  or its metadata by hand. A `done` item drops only `worktree:<path>` from the
  register.
- **Dirty or unpushed worktrees** reach step 5; the `kvb-git-worktree-orphans`
  skill finds the abandoned ones among them.
