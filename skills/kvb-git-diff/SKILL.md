---
name: kvb-git-diff
description: >
  Approve staged commits in the Agent Orchestrator; the commit skills run it.
---

The commit skills run this where they ask for the commit approval. A hub
approval is the operator's word for one commit, the exact tree it names, only
once the operator's pinned passkey signature over it verifies here.

1. Render the page. `<repo>` is the repository's name, `<branch>` the
   branch with every `/` as `-`, `<base>` the branch's base and `<table>` a
   file under `/tmp` holding the kvb-check-score commit table:

   ```bash
   pkgmgr review --out /tmp/kvb-git-diff/<repo>-<branch>.html --max-file-lines 400 --base <base> --note <table>
   ```

2. Call the kvb-orchestrator MCP tool `review_request` with `repo` (what
   `git rev-parse --path-format=absolute --git-common-dir` prints),
   `worktree` (what `git rev-parse --show-toplevel` prints), `branch` (what
   `git symbolic-ref --short HEAD` prints), `tree` (what `git write-tree`
   prints), `title` (the commit subject), `page` (the `--out` path), `notes`
   (the commit table), `gate` (`pass` when every gate the calling skill ran is green, else
   `fail`) and `score` (the kvb-check-score line). Only a `pass` review can
   be approved in bulk or by a rule. Tell the operator in one line that the
   review waits in the hub at the `url` it returns, written out as plain
   text: chat links do not open for this operator.
3. Call `review_wait` with its `id` and `timeout_seconds` 240 until the
   status is no longer `pending`.
4. `approved`: in the worktree, verify the operator's passkey signature
   first, `<gate>` being the `gate` from step 2:

   ```bash
   python3 ~/.local/share/kvb-orchestrator/client/approval.py verify --port 8737 --approvers ~/.config/kvb-orchestrator/approvers.json --replay /tmp/kvb-orchestrator-approvals/commit.json --review <id> --gate <gate>
   ```

   Exit 0 only: commit as the calling skill says. Any other exit,
   `rejected`, or the tree changed: no commit; report the printed reason.

The hub is unreachable (no kvb-orchestrator tools, or a call cannot connect), or the
verify step refused: ask the calling skill's normal approval question in
chat instead.
