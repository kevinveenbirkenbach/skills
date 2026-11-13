# Journal

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
