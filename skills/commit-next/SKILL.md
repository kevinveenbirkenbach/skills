---
name: commit-next
description: >
  Commit the staged bundle with --no-verify, then stage the next logical
  bundle and brief the operator on it. Trigger on /commit-next or when the
  operator asks to commit and stage the next bundle in one step. Portable
  across projects.
---

1. Run the commit-no-verify skill on the currently staged changes
   (comments-clean audit first, then `git commit --no-verify`, exact
   staging index only).
2. Group the remaining uncommitted changes into logical bundles (one
   concern per bundle: same failure class, same mechanism, or same role)
   and stage the next one; never mix concerns to save a commit.
3. For the newly staged bundle run the explain skill (what the changes do
   and how the pieces interact, file:line-anchored) followed by the
   confidence skill (fix confidence, break risk, evidence, residuals).
4. Close with what remains unstaged and wait for the operator's commit
   decision; never auto-commit the newly staged bundle.
