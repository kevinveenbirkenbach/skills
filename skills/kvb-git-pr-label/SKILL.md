---
name: kvb-git-pr-label
description: >
  Label pull requests `hotfix` and `90/5` from evidence; kvb-git-pr-create
  runs it.
---

Two labels, each set only with its evidence and removed when it no longer
holds:

- **`hotfix`**: the pull request targets the default branch and fixes a
  failure on it, a red default-branch run or an issue that reproduces there;
  name the run or issue.
- **`90/5`**: the pull request meets the bar of the `kvb-org-split` skill (fix
  confidence of at least 90 %, break risk under 5 %), from the
  `kvb-check-confidence` numbers in its body or freshly assessed, and only
  after the project's full quality gate passed on the PR's exact head; a
  hotfix takes the next free gate slot.

## Procedure

1. Target: the pull request named, else the current branch's (`gh pr view
   --json number,baseRefName,headRefName,isDraft,labels,body`); the default
   branch from `gh repo view --json defaultBranchRef`.
2. Judge both labels with their evidence.
3. A missing label is created once: `gh label create hotfix --color B60205
   --description "Fixes a failure on the default branch"`, `gh label create
   90/5 --color 0E8A16 --description "Fix confidence >= 90 %, break risk < 5 %"`.
4. Standalone, confirm the changes with one `AskUserQuestion`; from
   `kvb-git-pr-create`, its confirmation covers them.
5. `gh pr edit <pr> --add-label <l>` or `--remove-label <l>`. A draft that
   gains `90/5` also gets `gh pr ready <pr>`.

## Output

| PR | Label | Change | Evidence |
