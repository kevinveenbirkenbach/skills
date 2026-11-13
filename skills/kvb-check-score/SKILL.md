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

Each flag replaces the two lines; values, gate and exit code stay:

- `--table`: one markdown table, `| 🎯 Fix | 💥 Break | 💸 Tokens |
  ⏱️ Velocity | 🛡️ Security | 🏆 Score | Gate |`.
- `--commit-table <repo>`: that table led by `🌿 Branch | 📊 Diff stat`
  from git, 📁 worktree path below, alone in a code block. Every commit
  block is this table; after the commit, `--commit <sha>` shows that commit's diff stat
  and a `🔖 Commit` column.
- `--message-block`: one value per line, `🎯 Fix: <f> %` through
  `🏆 Score: <n>` and `🚦 Gate: <verdict>`. Every commit message carries it
  as its own paragraph right before the `Co-Authored-By` line, passed as one
  `-m` argument, so the approval prompt and git history show the values.

On a skill change add `--value <n:n|?>`, the quotient of the 💰 line (`?`
while it has no value): a `💰 Value` column after `💸 Tokens`, or line
after `🛡️ Security`. It changes neither score nor gate; alone it is a usage
error.

## Journal

Each `--message-block` render appends one row to
`${AGENTS_COUNCIL_ROOT:-/tmp/agents-council}/scores.jsonl`: time, origin
remote, top level path, branch, `sha` null, the six values and the block's
digest. The hub's burndown draws it as overlays; no gate reads it. A failed
append prints one stderr line and keeps the exit code; a linked council
root or a link, FIFO or other non-regular file at the journal fails it
without blocking, through `nofollow.py` of `kvb-org-organize`; when that
helper is missing or unusable, the line names it. A new council root gets mode
0700, a new journal 0600.

The journal lives in `/tmp`, so a reboot or another PC starts empty. Refill
it from the blocks in git history, without a model:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/backfill.py --repo <dir>... [--since <rev>] [--labels <file>]
```

It reads every local and origin branch, takes the last block of each commit
message, old labels included, and adds one row per commit not yet keyed by
(remote, sha), so a second run or another clone adds nothing. The branch is
the one whose first-parent line holds the commit, the default branch first,
else the one a merge subject names. An unknown label is reported once and
skipped.
