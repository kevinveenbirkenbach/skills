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
   it, the full staged diff (`git diff --cached`), then the commit table of
   the kvb-check-score skill (`score.py ... --commit-table <worktree>`):
   📁 worktree, 🌿 branch, 📊 staged diff stat, then fix, break, efficiency,
   speed, security, score and gate of the staged bundle, as the
   kvb-check-confidence skill produces them: break risk derived through the
   kvb-check-break-risk skill, never estimated.
3. Approval-prompt duty: the commit call's approval prompt (Claude Code: the
   Bash `description`; other runtimes: their prompt text) names the worktree
   path, the branch, the diff stat and the score values (🎯 fix, 💥 break,
   🌱 efficiency, ⚡ speed, 🛡️ security, 🏆 score). Missing any item: do not
   send the call. Gate exit 4 (critical security finding) means no commit:
   the call is never sent, not even on the operator's word; fix and rescan
   first. Exit 1 (below 90/5) is shown, the operator's word decides; exit 3
   means ask the operator again before the commit, naming each cause the
   gate prints. The same duty holds for every call that creates a commit,
   `git merge` included (there the incoming diff stat, and the incoming diff
   in the message before).
4. Commit exactly the staging index with `git commit --no-verify` and a
   Conventional-Commits message derived from the staged diff; never add
   unstaged files, never push.
5. Report the created commit hash, the commit table again with
   `--commit <hash>` (the committed diff stat and a 🔖 Commit column), and
   what remains uncommitted.
