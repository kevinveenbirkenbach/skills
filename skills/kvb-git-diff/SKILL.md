---
name: kvb-git-diff
description: >
  Approve staged commits in the Agent Orchestrator; commit skills run it.
---

Commit skills run this for the commit approval. A hub approval is the
operator's word for one commit, its exact tree, once the pinned passkey
signature verifies here. Placeholders, fallbacks and lifetime:
`reference.md` next to this file; the commit table:
`${CLAUDE_SKILL_DIR}/../kvb-check-confidence/chain.md`.

1. Render the page:

   ```bash
   pkgmgr review --out <pages>/<repo>-<branch>.html --max-file-lines 400 --base <base> --note <table>
   ```

2. Request the review in the worktree; `<gate>` is `pass` when every gate
   the calling skill ran is green, else `fail`. Tell the operator the
   printed `url` in plain text:

   ```bash
   python3 ~/.local/share/kvb-orchestrator/client/approval.py request --port 8737 --title "<subject>" --page <pages>/<repo>-<branch>.html --notes <table> --gate <gate> --score "<score line>" --agent "<agent>"
   ```

3. Call `review_wait` with its `id` and `timeout_seconds` 240 until the
   status is no longer `pending`.
4. `approved`: verify in the worktree:

   ```bash
   python3 ~/.local/share/kvb-orchestrator/client/approval.py verify --port 8737 --approvers ~/.config/kvb-orchestrator/approvers.json --replay <approvals>/commit.json --review <id> --gate <gate>
   ```

   Exit 0 only: commit as the calling skill says. Else, `rejected` or a
   changed tree: no commit; report the reason. `superseded`: wait on its
   `superseded_by`.

No kvb-orchestrator tools, or verify refused: ask the calling skill's
approval question in chat.
