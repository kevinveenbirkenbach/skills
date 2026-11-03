---
name: kvb-git-commit-no-verify
description: >
  Commit the staged changes with --no-verify. Trigger on /kvb-git-commit-no-verify or
  any request for a no-verify commit; invoking it IS the per-commit
  authorization --no-verify requires, never carried over to later commits.
---

1. Run the kvb-code-no-comments audit over the staged and unstaged changes first,
   then the kvb-check-legal check over the staging index. A legal blocker stops
   here.
2. Show four lines in the message right before the `git commit` call, never
   only after it:
   - **Worktree**: absolute path from `git rev-parse --show-toplevel`.
   - **Branch**: `git branch --show-current`, or `detached at <short sha>`.
   - **Fix confidence** of the staged bundle, from the kvb-check-confidence
     skill.
   - **Break risk** of the staged bundle, derived through the
     kvb-check-break-risk skill.
3. Commit exactly the staging index with `git commit --no-verify` and a
   Conventional-Commits message derived from the staged diff; never add
   unstaged files, never push.
4. Report the created commit hash and what remains uncommitted.
