---
name: kvb-check-score
description: >
  Score fix, break, tokens, velocity and security; run wherever confidence is reported.
---

Run it wherever fix confidence and break risk are reported: every
`kvb-check-confidence` block, stage summary, fix report and commit block.
Paste its two lines verbatim; they replace prose numbers.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/score.py --fix <0-100> --break <0-100> --efficiency <n|-|new> --speed <n|-> --security <n|~n> --critical <count>
```

| Emoji | Value | Source |
| --- | --- | --- |
| 🎯 | fix confidence | `kvb-check-confidence` |
| 💥 | break risk | `kvb-check-break-risk` |
| 💸 | tokens, `--efficiency` | `tokens.py` (skills) or `measure.py` (code) of `kvb-check-efficiency` |
| ⏱️ | velocity, `--speed` | `measure.py`, see `kvb-check-speed` |
| 🛡️ | security, critical count | `security.py` of `kvb-check-security`; `~<n>` from a review by hand |
| 💰 | cost:value quotient, tables and message block only | 💰 line of `tokens.py` (skills) of `kvb-check-efficiency` |
| 🏆 | score | this script |

Emojis and labels come from `labels.json`, one entry per metric key with
its former labels (Cost, Efficiency, Time, Speed); change a label there,
nowhere else.

Tokens and velocity: after over base in percent, over 100 worse. `-` means not
measured or not relevant (skills have no velocity) and counts as
100; it shows as `–`. `new` (changed skill text without a base) counts as 100
in the score, yet still asks. Never invent a value: measure it or pass `-`.

Score = `fix * (100 - break) / 100 * 100 / tokens * 100 / velocity * security / 100`,
capped to 0..100 and rounded.

## Gate

The second line is the verdict, first match wins:

- `⛔ gate: critical security finding: do not commit` (exit 4): the commit
  call is not sent, not even on an earlier approval. Fix the finding,
  rescan, score again.
- `⛔ gate: fix <f> % < 90` or `⛔ gate: break <b> % > 5` (exit 1): the 90/5
  rule fails, which bars PR labels and the split bar, not a commit: show it
  in the block and commit only on the operator's word. Close the gap as the
  last section of `kvb-check-break-risk` says.
- `⚠️ gate: <causes>: ask the operator before the commit` (exit 3), naming
  each of `tokens <c> % > 100`, `velocity <t> % > 100` and
  `security <n> % < 100`: ask with the block what the cost buys or why each
  finding is acceptable; commit only on a yes, never carried over to
  another commit.
- `✅ gate: 90/5, tokens and velocity <= 100, security 100 %` (exit 0):
  commit as usual. 90/5 still needs `gate: green` of `kvb-check-gate`.
- Exit 2: usage error, a malformed `labels.json` or a `--commit-table`
  repository git cannot read, with one stderr line and nothing on stdout;
  fix the cause and score again. A critical finding still exits 4 then.

## Tables and message block

Every commit block is the `--commit-table` and every commit message carries
the `--message-block` paragraph right before the `Co-Authored-By` line.
Read `tables.md` next to this file before using `--table`,
`--commit-table`, `--message-block` or `--value`.

## Journal

Each `--message-block` render appends a row to the score journal the hub's
burndown draws; no gate reads it. Read `journal.md` next to this file
before reading or refilling it.
