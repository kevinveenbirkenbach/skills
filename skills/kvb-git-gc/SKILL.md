---
name: kvb-git-gc
description: >
  Remove merged branches and worktrees. Trigger on "branches aufräumen",
  "worktrees aufräumen".
---

`pkgmgr gc` runs the worktree cleanup and the branch cleanup in one pass: a
merged worktree goes together with its local and remote branches, a pushed
but unmerged clean worktree goes while its branch stays, and a merged branch
without a worktree goes. This skill adds only the agent discipline: run the
steps of the `kvb-git-branch-cleanup` skill
(`${CLAUDE_SKILL_DIR}/../kvb-git-branch-cleanup/SKILL.md`, with its
`apply.md` and `unmerged.md`) with these changes.

## Changes

- **Claim**: `work/gc-<repo>`, or `work/gc-all` for every repository. The
  apply takes stacks down with their volumes, so the chair's grant comes
  first.
- **Dry run**: `pkgmgr gc --json --sizes --min-age 24 --merged-into <line>`,
  `--all` only on the operator's word, output to `/tmp/gc-<N>.json`.
- **Worktree items**: the hook, sandbox and EBUSY rules of the
  `kvb-git-worktree-cleanup` skill hold for every item with a worktree.
- **Apply**: `pkgmgr gc --apply --json --branch <name or path>`, one
  `--branch` per picked item, `| tee /tmp/gc-apply-<N>.json`, handed to the
  operator from an agent sandbox.
