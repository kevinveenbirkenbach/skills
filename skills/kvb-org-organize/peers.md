# Coordinating a failure or fix with peers

`kvb-org-coordinate`, `kvb-ci-triage`, `kvb-code-tune`, `kvb-org-split` and
`kvb-cleanup` follow these steps.

1. **Look**: `council.py list`, the `kvb-org-rasci` register, the news and the
   refs (the kvb-git-merge-fix skill's `find_fix.py`). A claim or a committed
   fix answers the question without a message.
2. **Claim** the office (Election in `SKILL.md`).
3. **Ask** (in Claude Code: `ListAgents`, then `SendMessage`) only the peers
   whose lines the work touches, the lineage owners (`lineage.md`) and, for
   capacity, the chair. One batched message per peer: what you claimed, the
   evidence (failing line quoted literally, run id, measurement), the
   suspected cause marked as a thesis, and the question "Already known or
   fixed on your side? Reply with a SHA or branch, or 'none'." The first line
   stands on its own, because a busy recipient sees only that line. In the
   register the peers asked are C, the chair that grants capacity is S.
4. **Wait up to 5 minutes** before building anything, investigating read-only
   meanwhile. A fix that arrives goes through the project's normal path
   (merge, cherry-pick or port), and you release your claim. Silence is
   neither a "no" nor a competing claim: after 5 minutes, proceed.
5. **Report** to the same peers through `news.py post --to <name>`: commit,
   branch, what changed, the evidence it works, and the merge it reaches them
   by; an abandoned or failed attempt too. In the register, enter the peers
   told as I and mark every key result the evidence proves as met. Then
   release the claim: the task ends `done`, or `stopped` while a key result is
   open.
