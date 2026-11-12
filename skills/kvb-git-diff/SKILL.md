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

2. Request the review in the worktree; it ships the staged diff, every file
   MEDUSA's secret rules or an armour line flag by stat only, so the hub
   shows it on the card. `<gate>` is
   `pass` when every gate the calling skill ran is green, else `fail`;
   `<agent>` your agent name, which inline feedback is posted to:

   ```bash
   python3 ~/.local/share/kvb-orchestrator/client/approval.py request --port 8737 --title "<subject>" --page /tmp/kvb-git-diff/<repo>-<branch>.html --notes <table> --gate <gate> --score "<score line>" --agent "<agent>"
   ```

   Only a `pass` review can be approved in bulk or by a rule. Tell the
   operator in one line that the review waits in the hub at the `url` it
   prints, written out as plain text: chat links do not open for this
   operator. Without the script, the MCP tool `review_request` takes the
   same fields without the diff.
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
