# Values, formula and labels

The `kvb-check-score` skill reads this file for what a value means and how
the score comes about. Each value's source is listed in the shared chain
rules of `kvb-check-confidence` (`chain.md`).

## Values

Tokens and velocity: after over base in percent, over 100 worse. `-` means
not measured or not relevant (skills have no velocity) and counts as 100; it
shows as `–`. `new` (changed skill text without a base) counts as 100 in the
score, yet still asks.

## Formula

Score = `fix * (100 - break) / 100 * 100 / tokens * 100 / velocity *
security / 100`, capped to 0..100 and rounded.

## Labels

Emojis and labels come from `labels.json`, one entry per metric key with
its former labels (Cost, Efficiency, Time, Speed); change a label there,
nowhere else.

## Gate lines

- `⛔ gate: critical security finding: do not commit` (exit 4): the commit
  call is not sent, not even on an earlier approval.
- `⛔ gate: fix <f> % < 90` or `⛔ gate: break <b> % > 5` (exit 1): the 90/5
  rule fails, which bars PR labels and the split bar, not a commit: show it
  in the block. Close the gap as the last section of `kvb-check-break-risk`
  says.
- `⚠️ gate: <causes>: ask the operator before the commit` (exit 3), naming
  each of `tokens <c> % > 100`, `velocity <t> % > 100` and
  `security <n> % < 100`: ask with the block; the yes never carries over to
  another commit.
- `✅ gate: 90/5, tokens and velocity <= 100, security 100 %` (exit 0).
- Exit 2: usage error, a malformed `labels.json` or a `--commit-table`
  repository git cannot read, with one stderr line and nothing on stdout. A
  critical finding still exits 4 then.

## Tables and message block

Every commit block is the `--commit-table` and every commit message carries
the `--message-block` paragraph right before the trailers; for a commit,
`scripts/block.py` runs every measuring script and prints both, as step 2
of `kvb-git-commit-no-verify` says. `tables.md` details each flag.

## Journal

Each `--message-block` render appends a row to the score journal the hub's
burndown draws; no gate reads it. `journal.md` details it.
