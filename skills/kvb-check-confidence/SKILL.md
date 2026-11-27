---
name: kvb-check-confidence
description: >
  Report calibrated fix confidence and break risk unprompted whenever you
  stage changes, declare a fix or bundle ready, or summarize committable or
  deployable work.
---

Every stage summary, fix report or ready-to-commit bundle ends with the
`kvb-check-score` block. Invoke `kvb-check-break-risk` before writing it and
report its number, never your own.

1. **Fix confidence** and **break risk**, two percentages.
2. **Score**: for a commit `block.py`, as step 2 of
   `kvb-git-commit-no-verify` says; else
   `${CLAUDE_SKILL_DIR}/../kvb-check-score/scripts/score.py` with both and
   the flags it lists. Exit 4 forbids the commit.
3. **Evidence**: the strongest proof lines, proven or derived.
4. **Residuals** per number.

Read `chain.md` next to this file before every report.

Objective: the `kvb-skill-tune` skill's **Objective** section; two figures
with residuals replace a hedging paragraph.
