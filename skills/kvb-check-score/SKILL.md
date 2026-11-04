---
name: kvb-check-score
description: >
  Score fix, break, efficiency and speed; run wherever confidence is reported.
---

Run it wherever fix confidence and break risk are reported: every
`kvb-check-confidence` block, stage summary, fix report and commit block.
One script call prints two lines; paste them verbatim, they replace prose
numbers.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/score.py --fix <0-100> --break <0-100> --efficiency <n|-|new> --speed <n|->
```

| Emoji | Value | Source |
| --- | --- | --- |
| 🎯 | fix confidence | `kvb-check-confidence` |
| 💥 | break risk | `kvb-check-break-risk` |
| 🌱 | efficiency | `tokens.py` (skills) or `measure.py` (code) of `kvb-check-efficiency` |
| ⚡ | speed | `measure.py`, see `kvb-check-speed` |
| 🏆 | score | this script |

`-` means not measured or not relevant (skills have no speed) and counts as
100; it shows as `–`. `new` (changed skill text without a base) counts as 100
in the score, yet still asks. Never invent a value: measure it or pass `-`.

Score = `fix * (100 - break) / 100 * 100 / efficiency * 100 / speed`,
capped to 0..100 and rounded.

## Gate

The second line is the verdict:

- `✅ gate: 90/5, efficiency and speed <= 100` (exit 0): commit as usual.
  90/5 still needs `gate: green` of `kvb-check-gate`.
- `⛔ gate: fix <f> % < 90` or `⛔ gate: break <b> % > 5` (exit 1): the 90/5
  rule fails, which bars PR labels and the split bar, not a commit: show it
  in the block and commit only on the operator's word. Close the gap as the
  last section of `kvb-check-break-risk` says.
- `⚠️ gate: efficiency <e> % > 100: ask the operator before the commit`, the
  same for speed (exit 3): the change costs more than its base. Before the
  commit, ask the operator with both lines and what the extra cost buys;
  commit only on a yes, which never carries over to another commit.
- Exit 2: usage error.

## Commit blocks

A commit block puts one line above the two:

```text
📁 <worktree> · 🌿 <branch> · 📊 <git diff --cached --shortstat>
🎯 fix 95 % · 💥 break 2 % · 🌱 efficiency 97 % · ⚡ speed – · 🏆 score 96
✅ gate: 90/5, efficiency and speed <= 100
```
