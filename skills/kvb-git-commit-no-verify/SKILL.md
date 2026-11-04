---
name: kvb-git-commit-no-verify
description: >
  Commit the staged changes with --no-verify. Trigger on any no-verify commit
  request; invoking it IS the per-commit --no-verify authorization, never
  carried over to later commits.
---

1. Run the kvb-code-no-comments audit over the staged and unstaged changes first,
   then the kvb-check-legal check over the staging index. A legal blocker stops
   here.
2. Show in the message right before the `git commit` call, never only after
   it, the full staged diff (`git diff --cached`), then the score block:
   - 📁 **Worktree**: absolute path from `git rev-parse --show-toplevel`.
   - 🌿 **Branch**: `git branch --show-current`, or `detached at <short sha>`.
   - 📊 **Diff stat** of what gets committed: `git diff --cached
     --shortstat`, e.g. `7 files +163/-108`.
   - The score line and gate line of the kvb-check-score skill for the staged
     bundle, as the kvb-check-confidence skill produces them: break risk
     derived through the kvb-check-break-risk skill, never estimated.
3. Approval-prompt duty: the commit call's approval prompt (Claude Code: the
   Bash `description`; other runtimes: their prompt text) names the worktree
   path, the branch, the diff stat and the score values (fix, break,
   efficiency, speed, score). Missing any item: do not send the call. Gate
   exit 1 (below 90/5) is shown, the operator's word decides; exit 3 means
   ask the operator again before the commit, naming the cause the gate line
   prints. The same duty holds for
   every call that creates a commit, `git merge` included (there the
   incoming diff stat, and the incoming diff in the message before).
4. Commit exactly the staging index with `git commit --no-verify` and a
   Conventional-Commits message derived from the staged diff; never add
   unstaged files, never push.
5. Report the created commit hash and what remains uncommitted.
