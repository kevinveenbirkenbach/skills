---
name: kvb-match
description: >
  Add finished stages as hub Match cards.
---

The operator decides every waiting commit and operator command as a card in
the hub's Match view under Tasks. The cards come from the hub's review queue
and the operator rows; this skill only adds to them and shows them.
`${CLAUDE_SKILL_DIR}/scripts/match.py` holds the steps.

1. Once a stage is finished, add it in the worktree. `<gate>` is `pass`
   when every gate the calling skill ran is green, else `fail`:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/match.py add --repo "$PWD" --title "<subject>" --score "<score line>" --gate <gate> --agent "<agent>"
   ```

   It prints the review `id`. The card shows the patch and tree of that
   moment; change the stage afterwards and the card turns `stale`, so add it
   again.
2. An operator row's card shows the files its command names as they were
   when it appeared. After changing one, take it again:
   `match.py add --task <operator/slug>`.
3. `match.py list` prints every card and marks a commit card whose staged
   tree changed as stale in the hub; `match.py show <card>` prints its patch
   or its command with the payload files.
4. Wait for the decision as `kvb-git-diff` does, from its step 3 on.
