---
name: kvb-git-pr-create
description: >
  Open a pull request for the current branch: push handed over, Closes lines,
  labels.
---

Opening a pull request is outward-facing and needs the branch on the remote,
which only the operator pushes. Nothing is created before the operator
confirms it.

## Procedure

1. **Check**: the branch is committed and clean, branched from the default
   branch (`gh repo view --json defaultBranchRef`), and has no open pull
   request yet (`gh pr list --head <branch>`).
2. **Assess** the branch with the `kvb-check-confidence` skill: its
   `kvb-check-score` block and residuals.
3. **Push**: hand the operator `gipsn` in the worktree through the
   `kvb-org-operator` skill, and continue once `git ls-remote --heads origin
   <branch>` shows the branch's head commit.
4. **Body**, written to a scratch file: what changed and why, the test
   evidence, the score block, and one `Closes #<n>` line per issue the
   branch fixes, each verified as the `kvb-git-issue-close` skill does.
5. **Confirm** with one `AskUserQuestion`: title (Conventional Commits),
   base, state and labels. The state follows the bar of the `kvb-org-swarm`
   skill (fix confidence ≥ 90 %, break risk ≤ 5 %, cost and time
   ≤ 100 %): ready at or above it, a draft with the residuals in the body
   below it. A cost or time over 100 % goes into this question with
   its cause.
6. **Create**: `gh pr create --base <default> --head <branch> --title
   "<title>" --body-file <file>`, plus `--draft` below the bar.
7. **Label** with the `kvb-git-pr-label` skill.

## Output

| PR | Base | State | Labels | Closes |
