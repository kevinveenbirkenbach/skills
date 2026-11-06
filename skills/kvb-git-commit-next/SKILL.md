---
name: kvb-git-commit-next
description: >
  Search every branch for the staged fix, commit it with --no-verify, then
  stage and brief the next bundle.
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
   (kvb-code-clean pass and kvb-check-legal check first, then the
   full staged diff and the kvb-check-score commit table of 📁 worktree,
   🌿 branch, 📊 diff stat, scores with 🛡️ security and gate, then
   `git commit --no-verify`, exact staging index only, its message carrying
   the `score.py --message-block` paragraph right before the
   `Co-Authored-By` line as one `-m` argument, then the table again with the
   hash). Its approval-prompt duty is binding: the commit call's approval
   prompt names worktree, branch, diff stat and the score values with
   🛡️ security, and the message holds the block, or the call is not sent.
   Gate exit 4 (critical security finding): no commit, the call is never
   sent. Exit 1 is shown and the operator's word decides; exit 3 asks the
   operator again first, naming each cause.
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
5. For the newly staged bundle run the kvb-code-clean pass, then the
   kvb-think-explain skill (what the changes do and how the pieces
   interact, file:line-anchored), then the kvb-check-confidence skill (its
   kvb-check-score block with 🛡️ security from `security.py` of
   kvb-check-security, evidence, residuals).
6. Close with the staged bundle's commit table (`score.py ...
   --commit-table <worktree>`: 📁 worktree, 🌿 branch, 📊 diff stat, scores,
   gate), what remains unstaged, and wait for the operator's commit
   decision; never auto-commit the newly staged bundle. Ask through the
   kvb-git-diff skill: a hub approval is the operator's commit decision for
   that one bundle only once its `approval.py verify` step exits 0 on the
   exact staged tree; otherwise the chat question stays the fallback. A gate exit 4 says
   up front that the bundle cannot be committed until its critical finding
   is fixed.
