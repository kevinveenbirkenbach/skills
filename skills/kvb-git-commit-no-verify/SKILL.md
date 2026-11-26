---
name: kvb-git-commit-no-verify
description: >
  Commit the staged changes with --no-verify on request; invoking it IS the
  per-commit --no-verify authorization, never carried over to later commits.
---

1. Run the kvb-code-clean pass (comments, defaults, principles) over the
   staged and unstaged changes first, then the kvb-check-legal check over
   the staging index. A legal blocker stops here.
2. Score the staged bundle in one run, in the background with its output in
   a `/tmp` log:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/../kvb-check-score/scripts/block.py --repo <worktree> --base HEAD --fix <n> --break <n> [--transcripts ~/.claude/projects [--saves <tokens/day> --evidence "<line>"]] [-- <command...>]
   ```

   Fix confidence comes from the kvb-check-confidence skill, break risk
   derived through the kvb-check-break-risk skill, never estimated.
   `--transcripts` when skill text changed; `-- <command>` (the targeted
   tests or a CLI call of the changed code) when runnable code changed, and
   then the whole call runs inside
   `${CLAUDE_SKILL_DIR}/../kvb-org-queue/scripts/queue.py hold --kind test
   --task <task> --`. It prints the commit table (📁 worktree, 🌿 branch,
   📊 staged diff stat, fix, break, tokens, velocity, security, score,
   gate), the `gate.py status` verdict that 90/5 also needs, the message
   block and the call for step 5. Show the table and the verdict right
   before the `git commit` call, never only after it. Exit 2 names the
   failing script; `security.py exited 4` sends you to
   `${CLAUDE_SKILL_DIR}/../kvb-check-security/coverage.md`. Never print a
   diff in the chat, only its stat.
3. Approval-prompt duty: the commit call's approval prompt (Claude Code: the
   Bash `description`; other runtimes: their prompt text) names the worktree
   path, the branch, the diff stat and the score values of step 2. Missing
   any item: do not send the call. Gate exit 4 (critical security finding) means no commit:
   the call is never sent, not even on the operator's word; fix and rescan
   first. Exit 1 (below 90/5) is shown, the operator's word decides; exit 3
   means ask the operator again before the commit, naming each cause the
   gate prints. Ask through the kvb-git-diff skill: a hub approval is the
   operator's word for this one commit only once its `approval.py verify`
   step exits 0 on the exact staged tree; otherwise the chat question stays
   the fallback. The same duty holds for every commit-creating call (a
   merge: the incoming diff stat).
4. Commit exactly the staging index with `git commit --no-verify` and a
   Conventional-Commits message derived from the staged diff; never add
   unstaged files, never push. Message: `-m "<subject>" -m "<body>" -m
   "<message block of step 2>" --trailer "Created-with:
   https://s.veen.world/skills" --trailer "Co-Authored-By: ..."`. A
   commit-creating call without block or `Created-with`, upstream commits
   included, is not sent; a merge is `git merge --no-ff --no-commit`, then
   this commit. Every commit and PR skill takes both from here; a PR body
   ends with `Created with https://s.veen.world/skills`.
5. Report the created commit hash, the commit table again by the `after the
   commit:` call of step 2 with the hash filled in (the committed diff stat
   and a 🔖 Commit column), and what remains uncommitted.
