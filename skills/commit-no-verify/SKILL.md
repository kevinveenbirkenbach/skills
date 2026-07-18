---
name: commit-no-verify
description: >
  Commit the currently staged changes with --no-verify (skip the pre-commit
  hooks). Trigger on /commit-no-verify or when the operator asks for a
  no-verify commit in any wording. Invoking this skill IS the explicit
  per-commit authorization that --no-verify requires; it never carries over
  to later commits. Portable across projects.
---

1. Run the comments-clean audit over the staged and unstaged changes first.
2. Commit exactly the staging index with `git commit --no-verify` and a
   Conventional-Commits message derived from the staged diff; never add
   unstaged files, never push.
3. Report the created commit hash and what remains uncommitted.
