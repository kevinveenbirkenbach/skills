---
name: kvb-check-efficiency
description: >
  Token cost of skill edits, CPU, RAM and wall-clock velocity of code edits.
---

💸 Tokens is the share of the base's resources a change uses: under 100 %
it saves, over 100 % it costs more. Paste the script's lines, never a
paragraph about them. `<ref>` is where the change starts: `HEAD` for
uncommitted work, else the merge base with the default branch.

## Skills: tokens

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/tokens.py --repo <skills repo> --base <ref> --transcripts ~/.claude/projects [--value <tokens/day> --evidence "<one line>"]
```

It compares every changed `*.md` under `skills/` (untracked included) and
the listing of all `description:` words (`scripts/budget.py`) at `<ref>`
with the working tree. A file without base text prints `tokens new`,
counted as over 100. Skills have no velocity.

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

Start it where the command expects. It runs the command in a detached
`/tmp` worktree of `<ref>` and in the working tree, from the same relative
directory, compares CPU seconds and peak RSS, and removes the worktree.
Cost is the mean of the CPU and the RAM ratio.

- **Runs**: one per tree. Both values at most 100 end it; otherwise 4 more
  per tree, alternating, and the line reports the mean of all 5
  (`mean of 5`).
- **Other load**: other CPU load above 30 % or no `/proc/stat` makes it an
  estimate: velocity from the CPU-time ratio, values marked `~`, the line
  ending `(estimated: other load <x> %)`. Pass them without `~`; the exit
  code holds.
- **Command**: the change's targeted tests or a CLI call of the changed
  code, runnable on a clean checkout (no untracked build output, virtualenv
  or dependencies).
- **Every run** goes inside
  `${CLAUDE_SKILL_DIR}/../kvb-org-queue/scripts/queue.py hold --kind <kind>
  --task <register task> -- python3 <measure.py> ...`, in the background,
  by the `kvb-org-queue` skill; a cancelled wait there also exits 3, but
  prints no 💸 line.
- Report the run you made; never rerun for a better one.

## Code: velocity

⏱️ Velocity is the share of the base's wall-clock time a change needs,
`⏱️ velocity <p> % (wall <b>→<a> s)` in the same `measure.py` line; pass
it as `--speed` to `kvb-check-score`. Skills and code without a runnable
path (configuration, templates no command renders) pass `--speed -`, shown
as `–`; say why.

## Overhead: per call

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/overhead.py --skills <skills root> --runs <n> [--case <name>] [--flags=<python flags>]
```

One line per case (hooks, radio, register): wall ms median, min and max,
the child's CPU ms (steady under load), output bytes. Compare two roots
back to back.

## Exit codes

- `0`: at most 100.
- `3`: over 100, or new: pass the value to `kvb-check-score`; its gate asks
  the operator before the commit.
- `2`: usage error, or the command failed; the message names the tree, the
  exit code and the last stderr line. Fix the command, then measure.

`--json` prints the same figures as JSON.
