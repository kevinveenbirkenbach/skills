---
name: kvb-org-queue
description: >
  Run every heavy job (gate, deploy, build, swarm) through a deterministic
  queue instead of asking the chair: hotfix first, then register rank.
---

`${CLAUDE_SKILL_DIR}/scripts/queue.py` replaces asking the chair for heavy
slots with one queue that every waiting agent evaluates by the same rules.

## Run a heavy job

```bash
queue.py hold --kind <kind> --task <register task> -- <command>
```

Start it in the background (`run_in_background` or equivalent) and end the
turn: hold waits, runs the command on its grant and exits with its code.

- `<kind>`: a key of `slot_need_gb` in `~/.config/agents-council/config.json`.
- `<register task>`: your open `kvb-org-rasci` task; its rank places you.
- `--hotfix <slug>`: the job proves the register row `hotfix/<slug>`
  (`kvb-git-hotfix`) and goes first.
- `--need-gb <N>` overrides the learned disk need.
- Start hold in the job's worktree: its git toplevel is the workdir. Other
  runtimes add `--session <id>`.
- In a worktree the command stays `gate.py run|hold` (`kvb-check-gate`):
  `queue.py hold ... -- python3 <gate.py> run ...`.

Light runs (no Docker, about a minute) self-admit with
`watch.py admit --kind test-nostack` (`kvb-org-organize`).

## Order and grant

Every 20 s each waiting hold evaluates the whole queue under one lock:

1. Hotfix jobs first, then the register rank (`rasci.py show`), one place
   earlier per whole hour waited, then arrival.
2. In that order, a job is blocked at disk stage stop or critical, at warn
   when it needs disk, during a radio-silence mayday, while its kind's slots
   are taken, or while its workdir runs another job.
3. A job whose need would cut below the stop threshold reserves that disk
   against smaller jobs behind it.
4. An unblocked job counts as granted for the jobs behind it: none takes its
   slot.
5. Kinds in `load_limits.kinds` also need CPU and RAM below the limits.

A waiting hold prints a stderr line when its position or reason changes.

## History and learning

Every finished job appends a row to the council's `queue-history.jsonl`:
signature (`make <target>`, `<script>.py <subcommand>`), kind, minutes, exit
code, and disk, RAM and CPU at the grant and at their 20 s extremes. The
`watch` hook of `kvb-org-organize` keeps them in
`~/.local/state/agents-council/` across reboots.

From the last 30 days, once 5 runs exist:

- per signature, the disk need is p90 disk taken plus 1 GB;
- per kind, the slot limit is how many p90 RAM and CPU shares fit between the
  median load at the grant and `load_limits`, at least 1.

Until then the seeds hold: `slot_need_gb[kind]` for disk, 1 slot per kind.
The optional `slot_limits {kind: N}` only caps a limit from above.

## Inspect and cancel

```bash
queue.py list
queue.py history
queue.py cancel <id>
```

`list` shows each job's position, need, wait, ETA and blocking reason; dead
holders drop out. The ETA adds the median minutes left of running jobs
and of the jobs ahead, `-` while one is unknown. `history` prints the learned
values per signature and per kind, with each limit's source. `cancel` removes
your own waiting job; its hold exits 3.

## Rules

- Never ask the chair for a heavy slot or announce a grant; the chair handles
  only exceptions such as a stuck queue or a hung job (`capacity.md` of
  `kvb-org-organize`).
- A running job is never cut short for the queue; only the operator orders
  one down, and `kvb-git-hotfix` may void a gate.
- With `queue_enforce: true`, the `block` hook (PreToolUse on Bash) refuses
  `heavy_commands` and `gate.py run|hold` outside `queue.py hold`.
- Without the config, hold exits 2: tell the operator and ask the chair
  (`kvb-org-organize`) until it exists.
