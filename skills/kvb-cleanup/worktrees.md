# Worktrees

## Inventory

Per worktree: size (`du -sh`), dirty state (`git status --short`), whether
its branch is pushed, and whether its HEAD is already contained in an
integration line: the default branch and every branch the project merges
features into (ask the operator or the project's memory which ones). With
`pkgmgr` installed, `pkgmgr branch gc --json --sizes --merged-into <line>`
(one per line) measures all of it; its merged-clean items go to the
`kvb-git-branch-gc` skill.

A clean worktree whose HEAD is in an integration line is medium risk: its
ignored files (`node_modules`, build output, evidence) are lost, no commit.

## Removal

Remove a worktree the way it was made: a slot worktree through the project's
teardown target (e.g. `make worktree-down`), run outside the sandbox; a plain
sidetree through `git worktree remove` without `--force`, which refuses a
dirty tree.
