---
name: kvb-check-score
description: >
  Score fix, break, tokens, velocity and security; run wherever confidence is reported.
---

Run it wherever fix confidence and break risk are reported; paste its two
lines verbatim:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/score.py --fix <0-100> --break <0-100> --efficiency <n|-|new> --speed <n|-> --security <n|~n> --critical <count>
```

Read `reference.md` next to this file for values, formula, labels and the
full gate lines; `tables.md` before `--table`, `--commit-table`,
`--message-block` or `--value`; `journal.md` before reading or refilling the
journal; `${CLAUDE_SKILL_DIR}/../kvb-check-confidence/chain.md` for sources.

## Gate

The second line is the verdict, first match wins:

- Exit 4, critical security finding: never send the commit call, even
  after an approval; fix, rescan, score again.
- Exit 1, fix under 90 or break over 5: 90/5 fails, which bars PR labels
  and the split bar; commit only on the operator's word.
- Exit 3, `ask the operator before the commit`: ask what the cost buys or
  why each finding is acceptable; commit only on a yes.
- Exit 0: commit as usual; 90/5 still needs `gate: green` of
  `kvb-check-gate`.
- Exit 2: usage error; fix the cause and score again.
