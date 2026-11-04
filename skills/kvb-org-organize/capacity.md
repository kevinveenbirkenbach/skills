# Chair, allocation and resource watch

## Allocation

- An operator-appointed allocator holds the chair: its claim says
  `appointed: operator`, and no election replaces it while its session runs and
  the operator has not ended the appointment.
- The chair keeps one queue: a hotfix gate (a branch from the default branch
  that fixes it) takes the next free gate or test slot before every other
  line, the rest follows the WSJF rank of the `kvb-org-wsjf` skill (it asks its
  subordinates for the Fibonacci estimates); a running gate is never cut short
  for a hotfix's slot, only when the hotfix voids it (`kvb-git-hotfix`). It
  answers every request with its queue position through
  `news.py post --to <name>` and sends the grant itself as a message (the
  requester acts on it), enforces the limits the operator set, and checks
  every grant with
  `watch.py admit --need-gb <N>` (or `--kind <slot>`; test kinds also need CPU
  and RAM below the configured limits).
- A running job (deploy, gate, test, swarm run, build) is never cut short to
  free capacity. The chair neither asks nor orders its owner to stop, take
  down or kill it, not for an operator-prioritised slot and not for a
  projected disk stop. It grants nothing new, frees idle items through the
  `kvb-cleanup` flow, asks the operator for an exception, or waits. An owner's
  own disk guard only alerts the chair and takes nothing down.

## Hung jobs

Besides a void by a missing merged hotfix (`kvb-git-hotfix`), the only
exception to "never cut short": an agent may end its own job, a stuck
step inside it, or a process its own ended session left behind, once at least
60 minutes passed without log progress and a probe shows standstill (no fresh
child process, no network traffic, CPU time not moving). It secures the live
state first, then reports the timestamp, the step, the probe and the command.
A peer's hung job goes to its owner, and to the operator when the owner does
not answer.

## Resource watch

The chair keeps the system from running out instead of reacting once it has.
`${CLAUDE_SKILL_DIR}/scripts/watch.py` measures as hooks in every session, so
no agent probes the disk by hand; it reads thresholds, job patterns, cleanup
commands and cache directories from `~/.config/agents-council/config.json`
(keys in the script's docstring) and stays silent below the thresholds.

- **Warn**: the chair and every session get the biggest consumers; the chair
  plans a cleanup and grants no large slot.
- **Stop**: new heavy jobs are blocked in every session (teardown commands
  never), and the hook runs the configured low-risk cleanup by itself; it
  skips every worktree where a gate or deploy process still runs.
- **Critical**: additionally a desktop alarm to the operator. Running jobs and
  their stacks still keep running; only the operator can make an exception.
- A measured fall that would reach the critical threshold within the
  projection window raises the stage by one at once.
- Caches together stay under their budget; the least recently used go first.

`watch.py status` shows the last measurement.
