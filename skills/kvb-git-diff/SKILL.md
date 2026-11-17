---
name: kvb-git-diff
description: >
  Approve staged commits in the Agent Orchestrator; commit skills run it.
---

The commit skills run this where they ask for the commit approval. A hub
approval is the operator's word for one commit, the exact tree it names, only
once the operator's pinned passkey signature over it verifies here.

1. Render the page. `<repo>` is the repository's name, `<branch>` the
   branch with every `/` as `-`, `<base>` the branch's base, `<table>` a
   file under `/tmp` holding the kvb-check-score commit table, `<pages>`
   and `<approvals>` the directories
   `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/councilroot.py dir pages`
   and `... dir approvals` print, in the council root the hub reads:

   ```bash
   pkgmgr review --out <pages>/<repo>-<branch>.html --max-file-lines 400 --base <base> --note <table>
   ```

2. Request the review in the worktree; it ships the staged diff, every file
   MEDUSA's secret rules or an armour line flag by stat only, so the hub
   shows it on the card. `<gate>` is
   `pass` when every gate the calling skill ran is green, else `fail`;
   `<agent>` your agent name, which inline feedback is posted to:

   ```bash
   python3 ~/.local/share/kvb-orchestrator/client/approval.py request --port 8737 --title "<subject>" --page <pages>/<repo>-<branch>.html --notes <table> --gate <gate> --score "<score line>" --agent "<agent>"
   ```

   Only a `pass` review can be approved in bulk or by a rule. Tell the
   operator the `url` it prints in one plain-text line; chat links do not
   open for this operator. Without the script or port 8737, the MCP tool
   `review_request` takes the same fields without the diff.
3. Call `review_wait` with its `id` and `timeout_seconds` 240 until the
   status is no longer `pending`.
4. `approved`: in the worktree, verify the operator's passkey signature
   first, `<gate>` being the `gate` from step 2:

   ```bash
   python3 ~/.local/share/kvb-orchestrator/client/approval.py verify --port 8737 --approvers ~/.config/kvb-orchestrator/approvers.json --replay <approvals>/commit.json --review <id> --gate <gate>
   ```

   Sandboxed without port 8737: save `review_wait`'s answer under `/tmp`,
   add `--record <file>`.
   Exit 0 only: commit as the calling skill says. Any other exit,
   `rejected`, or the tree changed: no commit; report the printed reason.

No kvb-orchestrator tools, or the verify step refused: ask the calling
skill's approval question in chat.
