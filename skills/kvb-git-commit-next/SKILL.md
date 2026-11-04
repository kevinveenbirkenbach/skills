---
name: kvb-git-commit-next
description: >
  Search every branch for the staged fix, commit it with --no-verify, then
  stage and brief the next bundle. Trigger on a request to commit and stage
  next.
---

1. Describe the staged bundle in one line, so a wrong search intent is
   visible. Then `git fetch --all --prune --tags` and hunt the staged fix
   across every ref with the kvb-git-merge-fix skill's `find_fix.py` (by
   `--grep`, by `-S`, by `--path`). Only the search runs here: never
   cherry-pick or merge, never touch the staging index or the tree.
2. A similar fix on another branch is a stop: run the kvb-think-dialectic
   skill on the two candidates (staged version as thesis, foreign commit as
   antithesis) until one survives, then present sha, branch, both diffs, the
   verdict and the recommended move (keep staged / take theirs / combine).
   Wait for the operator's decision; do not commit.
3. Nothing similar found, or the operator picked the staged version: run the
   kvb-git-commit-no-verify skill on the currently staged changes
   (kvb-code-no-comments audit and kvb-check-legal check first, then the
   full staged diff and its score block of 📁 worktree, 🌿 branch,
   📊 diff stat, score line and gate line, then `git commit --no-verify`,
   exact staging index only). Its approval-prompt duty is binding: the commit
   call's approval prompt names worktree, branch, diff stat and the score
   values, or the call is not sent. Gate exit 1 is shown and the operator's
   word decides; exit 3 asks the operator again first, naming the cause.
4. Group the remaining uncommitted changes into logical bundles (one concern
   per bundle: same failure class, mechanism or role) and stage the next one;
   never mix concerns to save a commit. Staging happens here and nowhere
   else: never stage merely to run a lint or a test. Checks that enumerate
   through `git ls-files` already see tracked, modified files and read the
   worktree; only an untracked NEW file needs `git add` to become visible.
   Path-scope every `git add` to the bundle: `git add -A` sweeps up the
   operator's own edits and local config. A file that carries two bundles is
   staged by line: `${CLAUDE_SKILL_DIR}/scripts/stage_hunks.py --repo
   <worktree> --file <path> --match <regex>`, first with `--dry-run`.
5. For the newly staged bundle run the kvb-think-explain skill (what the
   changes do and how the pieces interact, file:line-anchored), then the
   kvb-check-confidence skill (its kvb-check-score block, evidence,
   residuals).
6. Close with the staged bundle's score block (📁 worktree, 🌿 branch,
   📊 diff stat, score line, gate line), what remains unstaged, and wait for
   the operator's commit decision; never auto-commit the newly staged bundle.
