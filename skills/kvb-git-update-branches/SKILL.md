---
name: kvb-git-update-branches
description: >
  Merge main into open PRs or branches: the operator's own directly, others
  after consent.
---

Invoking this skill authorizes the merge commits it makes; pushing stays the
operator's. Branches are merged, never rebased.

## Step 1: scope and candidates

Pull requests, branches or both, as the operator said; ask when it is open.
`git fetch --all --prune`, then list the open branches with lag and owner:

```bash
gh pr list --state open --json number,headRefName,author,isCrossRepository > <tmp>/prs.json
branches.py --repo <repo> --remote origin --base main --email "<git user.email>" --login "<gh login>" --prs <tmp>/prs.json
```

`${CLAUDE_SKILL_DIR}/scripts/branches.py` drops branches already merged into
the base and marks `mine`: a pull request by the operator's login, or a
branch whose own commits all carry the operator's email. A row with
`behind 0` is current and skipped.

## Step 2: consent

The operator's own rows go on. For every other row run the `kvb-think-listen`
skill: one `AskUserQuestion` with `multiSelect: true` listing branch, pull
request, owner and lag, nothing preselected. Only the picks are updated.

## Step 3: update

- **Fork pull request**: no local merge; its `gh pr update-branch <n>` goes
  to the operator.
- **Any other branch**: in the worktree that already has it checked out,
  else a temporary one under `/tmp` (the repository's own worktree targets
  where it has them), `git merge --no-verify --no-edit origin/main`. On a
  conflict, `git merge --abort` and report the files; the `kvb-git-merge-fix`
  skill or the operator resolves it later.
- Remove the temporary worktrees afterwards.

## Step 4: hand over the pushes

Every updated branch's push and every `gh pr update-branch` goes to the
`kvb-org-operator` skill as an operator command.

## Output

| Branch | PR | Owner | Behind | Result | Push command |
