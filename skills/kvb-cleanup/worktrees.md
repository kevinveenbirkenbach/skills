# Worktrees

## Inventory

Per worktree: size (`du -sh`), dirty state, whether its branch is pushed and
whether its HEAD is in an integration line (the default branch and every
branch the project merges features into; ask the operator or the project's
memory). With `pkgmgr`, `pkgmgr gc --json --sizes --merged-into <line>`
(one per line) measures it all; its candidates go to the `kvb-git-gc` skill.
At `warn` or worse, or with worktrees on top of the report, add the largest of
`kvb-git-worktree-orphans --sizes`.

Clean and in a line: medium, its ignored files (`node_modules`, build output,
evidence) are lost. Dirty: a candidate only when every changed, staged and
untracked file is a blob at some branch tip and a detached HEAD is reachable
from another ref; else it is unique work and stays.

## Removal

The way it was made: a slot worktree through the project's teardown target
(e.g. `make worktree-down`), a sidetree through `git worktree remove`,
`--force` only for a dirty one cleared above. Never in an agent sandbox: its
read-only `.git/worktrees/<id>` mounts make git unregister and then fail with
`Device or resource busy`, container-owned files with `Permission denied`.
Hand the operator in one message, per worktree, its count of `find <wt> -not
-user "$USER" -prune | wc -l`, `sudo chown -R "$USER": <wt>` where it is not
0, then the removal command.
