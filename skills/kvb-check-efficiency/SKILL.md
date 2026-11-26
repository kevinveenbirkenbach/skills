---
name: kvb-check-efficiency
description: >
  Token cost of skill edits, CPU, RAM and wall-clock velocity of code edits.
---

💸 Tokens is the share of the base's resources a change uses: under 100 %
it saves, over 100 % it costs more. Paste the script's lines, never a
paragraph about them. `<ref>` is the commit the change
starts from: `HEAD` for uncommitted work, the merge base with the default
branch for a branch.

## Skills: tokens

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/tokens.py --repo <skills repo> --base <ref> --transcripts ~/.claude/projects [--value <tokens/day> --evidence "<one line>"]
```

It compares every changed `*.md` under `skills/`, untracked ones included,
at `<ref>` with the working tree, and the always-loaded listing: all
`description:` words, counted by the repository's `scripts/budget.py`.
Changed files without any base text print `tokens new`, which counts as
over 100. Skills have no velocity.

A second line, `💰 value 1:<n>` (`<n>:1` when value < cost), weighs both
per day and never changes the exit code; pass its quotient or `?` to
`kvb-check-score --value`.

- **Cost**: the listing words delta and each changed `SKILL.md`'s tokens
  delta times its daily requests, invocations and resident turns over the
  last 7 days' transcripts; the docstring of `tokens.py` holds the formula.
- **Value**: tokens/day saved, derived by one `--evidence` line, e.g.
  `"3829 SendMessage wakes/day x 10 % avoided x 43k"`; else `?:?`.
- **Measured**: once shipped, `tokens.py value --repo <repo> --since
  <commit> --transcripts <dir>` gives the median daily context tokens 7
  days before minus after; pass it as `--value`.

## Code: CPU and RAM

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/measure.py --base <ref> -- <command...>
```

Start it in the directory the command expects. It checks `<ref>` out as a
detached worktree under `/tmp`, runs the command there and in the working
tree from the same relative directory, compares CPU seconds and peak RSS,
and removes the worktree. Cost is the mean of the CPU and the RAM ratio.

- **Runs**: one per tree. Both values at most 100 end it; otherwise 4 more
  per tree, alternating, and the line reports the mean of all 5
  (`mean of 5`).
- **Other load**: CPU busy beyond the command's own above 30 %, or no
  `/proc/stat`, makes the result an estimate: velocity from the CPU-time
  ratio, both values marked `~`, the line ending in `(estimated: other load
  <x> %)`. Pass the numbers without `~`; the exit code holds.
- **Command**: the targeted tests of the change or a CLI call of the
  changed code, runnable on a clean checkout: the base worktree holds no
  untracked build output, virtualenv or dependency directory.
- **Every run** goes inside
  `${CLAUDE_SKILL_DIR}/../kvb-org-queue/scripts/queue.py hold --kind <kind>
  --task <register task> -- python3 <measure.py> ...`, in the background,
  by the `kvb-org-queue` skill; a cancelled wait there also exits 3, but
  prints no 💸 line.
- Report the run you made; never rerun to pick the best result.

## Code: velocity

⏱️ Velocity is the share of the base's wall-clock time a change needs,
`⏱️ velocity <p> % (wall <b>→<a> s)` in the same `measure.py` line; pass
it as `--speed` to `kvb-check-score`. Skills and code without a runnable
path (configuration, templates no command renders) pass `--speed -`, shown
as `–`; say why.

## Exit codes

- `0`: at most 100.
- `3`: over 100, or new: pass the value to `kvb-check-score`; its gate asks
  the operator before the commit.
- `2`: usage error, or the command failed; the message names the tree, the
  exit code and the last stderr line. Fix the command, then measure.

`--json` prints the same figures as JSON.
