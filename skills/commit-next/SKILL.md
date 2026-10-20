---
name: commit-next
description: >
  Fetch every branch and check whether the staged fix already exists
  elsewhere, then commit the staged bundle with --no-verify, stage the next
  logical bundle and brief the operator on it. Trigger on /commit-next or
  when the operator asks to commit and stage the next bundle in one step.
  Portable across projects.
---

1. `git fetch --all --prune --tags`, then hunt the staged fix across every
   ref with the merge-fix search steps (`git log --all` by `--grep`, by
   `-S<symbol>`, by path). Describe the staged bundle in one line first so a
   wrong search intent is visible. Only the search runs here — never
   cherry-pick or merge, and never touch the staging index or the tree.
2. A similar fix on another branch is a stop: run the dialectic skill on the
   two candidates (staged version as thesis, foreign commit as antithesis)
   until one survives, then present sha, branch, both diffs, the verdict and
   the recommended move (keep staged / take theirs / combine). Wait for the
   operator's decision; do not commit.
3. Nothing similar found, or the operator picked the staged version: run the
   commit-no-verify skill on the currently staged changes (comments-clean
   audit and advocate check first, then `git commit --no-verify`, exact
   staging index only).
4. Group the remaining uncommitted changes into logical bundles (one
   concern per bundle: same failure class, same mechanism, or same role)
   and stage the next one; never mix concerns to save a commit. Staging
   happens here and nowhere else: never stage merely to run a lint or a
   test. Repository checks that enumerate through `git ls-files` already
   see tracked, modified files and read the worktree; only an untracked
   NEW file needs `git add` to become visible. Path-scope every `git add`
   to the bundle — `git add -A` sweeps up the operator's own edits and
   their local config.
5. For the newly staged bundle run the explain skill (what the changes do
   and how the pieces interact, file:line-anchored) followed by the
   confidence skill (fix confidence, break risk, evidence, residuals).
6. Close with what remains unstaged and wait for the operator's commit
   decision; never auto-commit the newly staged bundle.
