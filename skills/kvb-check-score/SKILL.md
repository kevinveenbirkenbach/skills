---
name: kvb-check-score
description: >
  Score fix, break, efficiency, speed and security; run wherever confidence is reported.
---

Run it wherever fix confidence and break risk are reported: every
`kvb-check-confidence` block, stage summary, fix report and commit block.
One script call prints two lines; paste them verbatim, they replace prose
numbers.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/score.py --fix <0-100> --break <0-100> --efficiency <n|-|new> --speed <n|-> --security <n|~n> --critical <count>
```

| Emoji | Value | Source |
| --- | --- | --- |
| 🎯 | fix confidence | `kvb-check-confidence` |
| 💥 | break risk | `kvb-check-break-risk` |
| 🌱 | efficiency | `tokens.py` (skills) or `measure.py` (code) of `kvb-check-efficiency` |
| ⚡ | speed | `measure.py`, see `kvb-check-speed` |
| 🛡️ | security, critical count | `security.py` of `kvb-check-security`; `~<n>` from a review by hand |
| 🏆 | score | this script |

`-` means not measured or not relevant (skills have no speed) and counts as
100; it shows as `–`. `new` (changed skill text without a base) counts as 100
in the score, yet still asks. Never invent a value: measure it or pass `-`.

Score = `fix * (100 - break) / 100 * 100 / efficiency * 100 / speed * security / 100`,
capped to 0..100 and rounded.

## Gate

The second line is the verdict, first match wins:

- `⛔ gate: critical security finding: do not commit` (exit 4): the commit
  call is not sent, whatever else holds and whatever the operator approved
  before. Fix the finding, rescan, score again.
- `⛔ gate: fix <f> % < 90` or `⛔ gate: break <b> % > 5` (exit 1): the 90/5
  rule fails, which bars PR labels and the split bar, not a commit: show it
  in the block and commit only on the operator's word. Close the gap as the
  last section of `kvb-check-break-risk` says.
- `⚠️ gate: <causes>: ask the operator before the commit` (exit 3), naming
  each of `efficiency <e> % > 100`, `speed <s> % > 100` and
  `security <n> % < 100`: the change costs more than its base or carries
  findings. Before the commit, ask the operator with the block and what the
  cost buys or why each finding is acceptable; commit only on a yes, which
  never carries over to another commit.
- `✅ gate: 90/5, efficiency and speed <= 100, security 100 %` (exit 0):
  commit as usual. 90/5 still needs `gate: green` of `kvb-check-gate`.
- Exit 2: usage error.

## Tables

`--table` prints the same values as one markdown table instead of the two
lines:

```text
| 🎯 Fix | 💥 Break | 🌱 Efficiency | ⚡ Speed | 🛡️ Security | 🏆 Score | Gate |
```

`--commit-table <repo>` leads that table with `📁 Worktree | 🌿 Branch |
📊 Diff stat`, read from git: the top level, the current branch (or
`detached at <sha>`) and the staged `git diff --cached --shortstat` as
`<n> files +<added>/-<removed>`. Every commit block is this table. After the
commit, add `--commit <sha>`: the diff stat of that commit and a `🔖 Commit`
column.
