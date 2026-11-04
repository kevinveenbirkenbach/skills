---
name: kvb-check-efficiency
description: >
  Token cost of skill edits, CPU and RAM of code edits.
---

Efficiency is the share of its base's resources a change uses: under 100 %
it saves, over 100 % it costs more. One script call gives one line; paste
that line, never a paragraph about it. `<ref>` is the commit the change
starts from: `HEAD` for uncommitted work, the merge base with the default
branch for a branch.

## Skills: tokens

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/tokens.py --repo <skills repo> --base <ref>
```

It compares every changed `*.md` under `skills/`, untracked ones included,
at `<ref>` with the working tree, and the always-loaded listing: all
`description:` words, counted by the repository's `scripts/budget.py`.
Tokens are an estimate, characters / 4. Changed files without any base text
print `efficiency new`, which counts as over 100. Skills have no speed.

## Code: CPU and RAM

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/measure.py --base <ref> -- <command...>
```

Start it in the directory the command expects. It checks `<ref>` out as a
detached worktree under `/tmp`, runs the command there and in the working
tree from the same relative directory, compares CPU seconds and peak RSS,
and removes the worktree. Efficiency is the mean of the CPU and the RAM
ratio. The same run measures wall time for `kvb-check-speed`.

- **Runs**: one per tree. Both values at most 100 end it; otherwise 4 more
  per tree, alternating, and the line reports the mean of all 5
  (`mean of 5`).
- **Other load**: a 1 s sample of system CPU busy before and after, and per
  run the busy share beyond the command's own CPU time. Above 30 %, or
  unreadable without `/proc/stat`, the result is an estimate: speed comes
  from the CPU-time ratio, both values carry `~` and the line ends in
  `(estimated: other load <x> %)`. Pass the numbers without `~` to
  `kvb-check-score`; the exit code holds as for a measured result.
- **Command**: the targeted tests of the change or a CLI call of the
  changed code, runnable on a clean checkout: the base worktree holds no
  untracked build output, virtualenv or dependency directory.
- **Heavy commands** (Docker, deploys, whole suites) run only inside
  `${CLAUDE_SKILL_DIR}/../kvb-org-queue/scripts/queue.py hold --kind <kind>
  --task <register task> -- python3 <measure.py> ...`, in the background,
  by the `kvb-org-queue` skill; a cancelled wait there also exits 3, but
  prints no 🌱 line. A light one self-admits with
  `watch.py admit --kind test-nostack` of `kvb-org-organize`.
- Report the run you made; never rerun to pick the best result.

## Exit codes

- `0`: at most 100.
- `3`: over 100, or new: pass the value to `kvb-check-score`; its gate asks
  the operator before the commit.
- `2`: usage error, or the command failed; the message names the tree, the
  exit code and the last stderr line. Fix the command, then measure.

`--json` prints the same figures as JSON.
