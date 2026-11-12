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
turn: hold runs the command on its grant and exits with its code.

- `<kind>`: a key of `slot_need_gb` in `~/.claude/agents-council/config.json`.
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

Every 20 s each waiting hold evaluates the queue under one lock:

1. Hotfix jobs first, then the register rank (`rasci.py show`), one place
   earlier per whole hour waited, then arrival; an open `after` task holds a
   job.
2. In that order, a job is blocked at disk stage stop or critical, at warn
   when it needs disk, at memory stage stop, during a radio-silence mayday,
   while its kind's slots are taken, or while its workdir runs another job;
   `exclusive_kinds` run only beside `light_kinds`.
3. A job whose disk need would cut below the stop threshold, or whose
   footprint would push the running ones past `budget_percent`, reserves it
   against the jobs behind it but `light_kinds`, which meet only running and
   granted jobs, so a stream of light jobs can delay a heavy head; a job
   alone always fits.
4. An unblocked job counts as granted for the jobs behind it.
5. Every job, alone too, needs CPU, and RAM used plus what it and the
   running jobs may still take, below `load_limits`.

## History and learning

Every finished job appends a row (signature such as `<repo>: make <target>`,
kind, minutes, disk, RAM and CPU) to `queue-history.jsonl`; the
`kvb-org-organize` watch hook keeps it across reboots.

From the last 30 days, once 5 runs exist:

- per signature, the disk need is p90 disk taken plus 1 GB;
- per kind, the slot limit is how many p90 RAM and median CPU shares fit
  between the median load at the grant and `load_limits`, at least 1;
- per job, the footprint is its signature's share, else its kind's.

Until then the seeds hold: `slot_need_gb[kind]` for disk, 1 slot per kind,
the whole budget as footprint.
The optional `slot_limits {kind: N}` only caps a limit from above.

## Inspect and cancel

```bash
queue.py list
queue.py history
queue.py cancel <id>
```

`list` shows each job's position, ETA and blocking reason, `history` the
learned values, `cancel` removes your own waiting job.

## Rules

- Never ask the chair for a heavy slot or announce a grant; the chair handles
  only exceptions such as a stuck queue or a hung job (`capacity.md` of
  `kvb-org-organize`).
- A running job is never cut short for the queue; only the operator orders
  one down, and `kvb-git-hotfix` may void a gate.
- With `queue_enforce: true`, the `block` hook (PreToolUse on Bash) refuses
  `heavy_commands`, image builds, `make install|verify-*`, tests beyond one
  file and `gate.py run|hold` outside `queue.py hold`.
- Without the config, hold exits 2: tell the operator and ask the chair
  (`kvb-org-organize`) until it exists.
