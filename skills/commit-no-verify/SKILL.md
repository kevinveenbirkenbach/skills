---
name: commit-no-verify
description: >
  Commit the staged changes with --no-verify. Trigger on /commit-no-verify or
  any request for a no-verify commit; invoking it IS the per-commit
  authorization --no-verify requires, never carried over to later commits.
---

1. Run the comments-clean audit over the staged and unstaged changes first,
   then the advocate check over the staging index. An advocate blocker stops
   here.
2. Commit exactly the staging index with `git commit --no-verify` and a
   Conventional-Commits message derived from the staged diff; never add
   unstaged files, never push.
3. Report the created commit hash and what remains uncommitted.
