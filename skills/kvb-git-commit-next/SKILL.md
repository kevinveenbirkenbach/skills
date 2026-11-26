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
   antithesis) until one survives, then present sha, branch, both diff stats, the
   verdict and the recommended move (keep staged / take theirs / combine).
   Wait for the operator's decision; do not commit.
3. Nothing similar found, or the operator picked the staged version: run the
   kvb-git-commit-no-verify skill on the currently staged changes. Its
   steps bind unchanged: clean and legal passes, the `block.py` table and
   message block, the approval-prompt duty and the gate exits (4: never
   sent; 1: the operator's word; 3: ask again, naming each cause).
4. Group the remaining uncommitted changes into logical bundles (one concern
   per bundle: same failure class, mechanism or role) and stage the next one;
   never mix concerns to save a commit. Staging happens here and nowhere
   else: never stage merely to run a lint or a test. Checks enumerating
   `git ls-files` see tracked edits; only an untracked new file needs
   `git add` to be seen. Path-scope every `git add`: `-A` sweeps up the
   operator's edits and local config. A file that carries two bundles is
   staged by line: `${CLAUDE_SKILL_DIR}/scripts/stage_hunks.py --repo
   <worktree> --file <path> --match <regex>`, first with `--dry-run`.
5. For the newly staged bundle run the kvb-code-clean pass, then the
   kvb-think-explain skill (what the changes do and how the pieces
   interact, file:line-anchored), then the kvb-check-confidence skill (fix,
   break, evidence, residuals) and `block.py` as step 2 of
   kvb-git-commit-no-verify runs it.
6. Close with the staged bundle's `block.py` table and gate verdict, what
   remains unstaged, the `push` targets of `pkgmgr worktree
   flow --json` the branch flows into, and wait for the operator's commit
   decision; never auto-commit the newly staged bundle. Ask through the
   kvb-git-diff skill: a hub approval is the operator's commit decision for
   that one bundle only once its `approval.py verify` step exits 0 on the
   exact staged tree; else ask in chat. A gate exit 4 says
   up front that the bundle cannot be committed until its critical finding
   is fixed.
