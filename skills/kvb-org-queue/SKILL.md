---
name: kvb-org-queue
description: >
  Queue heavy jobs (gate, deploy, build, swarm) without the chair: hotfix,
  then rank; FIFO per worktree.
---

`${CLAUDE_SKILL_DIR}/scripts/queue.py` is one queue all waiting agents
evaluate alike, never the chair.

## Run a heavy job

```bash
queue.py hold --kind <kind> --task <register task> -- <command>
```

Background it and end the turn; hold runs the command on grant, exiting with
its code.

- `<kind>`: a key of `slot_need_gb` in `~/.claude/agents-council/config.json`.
- `<register task>`: your open `kvb-org-rasci` task; its rank places you.
- `--hotfix <slug>`: the job proves the register row `hotfix/<slug>`
  (`kvb-git-hotfix`) and goes first.
- `--need-gb <N>` overrides learned disk need.
- Start hold in the job's worktree: its git toplevel is the workdir. Other
  runtimes add `--session <id>`.
- In a worktree the command stays `gate.py run|hold` (`kvb-check-gate`):
  `queue.py hold ... -- python3 <gate.py> run ...`.

Light runs (`kvb-org-organize` Capacity) self-admit; anything else goes
through hold with kind `test`, and a light kind refuses it.

## Order and grant

Every 20 s each waiting hold evaluates the queue, locked:

1. Hotfixes first, then the register rank (`rasci.py show`), one place
   earlier per whole hour waited, then arrival; an open `after` task holds a
   job. Main first needs Main in `rasci.py agents` (else no tiebreak); a job
   aged an hour still passes Main's.
2. A job waits at disk stage stop or critical, at warn when it needs disk,
   at memory stage stop, during a radio-silence mayday, while its kind's
   slots are taken, or behind an earlier job of its worktree, compose stack
   or `INFINITO_INSTANCE` slot; a job passes one that can never start, a
   light job one awaiting only the machine, a hotfix all but hotfixes and
   running jobs; `exclusive_kinds` run
   only beside `light_kinds`.
3. A job fits if its disk need keeps the stop threshold free and its
   footprint the running ones within `budget_percent` (alone always), and
   passes blocked jobs, but the head (a blocked hotfix, an exclusive job
   running jobs keep out, one stuck a minute or an hour old, or for other
   lines a Main job whose line runs or awaits the machine) only taking
   nothing it lacks, its last slot included, and only light while it is a
   hotfix, exclusive or held by queue load.
4. An unblocked job counts as granted for the jobs behind it.
5. Every job, alone too, needs CPU, and RAM used plus what it and the
   running jobs may still take, below `load_limits`; outside load makes no
   head and holds no line.
6. A stall escalates itself (`ESCALATION` in queue.py).

## History and learning

Finished jobs teach disk need, slot limits and footprints via
`queue-history.jsonl`; read `learning.md` before changing a seed or limit.

## Inspect and cancel

```bash
queue.py list [--json]
queue.py history
queue.py cancel <id>
```

`list` shows position, ETA and blocking reason (`--json`: rule trace), `history` the learned values, `cancel` removes your waiting job.

## Rules

- Never ask the chair for a heavy slot or announce a grant; the chair handles
  only a stuck queue or hung job (`capacity.md` of `kvb-org-organize`).
- Only the operator, a `kvb-git-hotfix` gate void, or hold after 60 minutes
  of tree standstill (exit 124) cut a job short. `kvb-org-queue-cleanup`
  deletes only entries whose lock no living process holds.
- With `queue_enforce: true`, the `block` hook (PreToolUse on Bash) refuses
  `heavy_commands`, image builds, `make install|test*|quality*|verify-*`,
  tests beyond one unit file and `gate.py run|hold` outside `queue.py hold`.
- Without the config, hold exits 2: tell the operator, ask the chair
  (`kvb-org-organize`). Waiting holds reread it every poll, keeping the
  last good one.
