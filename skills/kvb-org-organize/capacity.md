# Chair, allocation and resource watch

## Allocation

- An operator-appointed allocator holds the chair: its claim says
  `appointed: operator`, and no election replaces it while its session runs and
  the operator has not ended the appointment.
- The queue of the `kvb-org-queue` skill grants heavy jobs by rule, with no
  request, position post or grant message: a hotfix gate (a branch from the
  default branch that fixes it, checked against its `hotfix/` register row)
  before every other line, the rest by the register rank, that is the
  operator's pins, then the WSJF of the `kvb-org-wsjf` skill; slot limits
  from `slot_limits` in the config, disk reserved per granted job, CPU and RAM
  through `watch.py`, nothing new at the stop stage or during a mayday. A
  running gate is never cut short for a hotfix's slot, only when the hotfix
  voids it (`kvb-git-hotfix`).
- The chair handles what the rule cannot: it collects the Fibonacci
  estimates (an unestimated task ranks last), places a job the rule leaves
  waiting too long, and carries out the operator's overrides. `queue.py list`
  shows the queue.
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
not answer. `queue.py hold` does this itself for a queued job: after 60
minutes without CPU, I/O or new process in its tree, no stopped member and no
docker, podman or ssh client, it records the stuck processes, ends the tree
and exits 124; `queue.py list` marks a run past three times its longest
learned one `suspect hung`.

## Resource watch

The chair keeps the system from running out instead of reacting once it has.
`${CLAUDE_SKILL_DIR}/scripts/watch.py` measures as hooks in every session, so
no agent probes the disk by hand; it reads thresholds, job patterns, cleanup
commands and cache directories from `~/.claude/agents-council/config.json`
(keys in the script's docstring; there because its hooks run outside the
sandbox, whose file rules keep it out of `~/.claude` unless a Docker daemon it
can reach mounts it, and the install denies agents' edits of that directory)
and stays silent below the thresholds.

- **Warn**: the chair and every session get the biggest consumers; the chair
  plans a cleanup and grants no large slot.
- **Stop**: new heavy jobs are blocked in every session (teardown commands
  never), and the hook runs the configured low-risk cleanup by itself; it
  skips every worktree where a gate or deploy process still runs. Its
  `docker image prune` removes only images whose repository and digest are
  both `<none>`, so pulls by digest stay; `system prune`, `rmi`, `image rm`
  and `compose down --rmi` are refused. An accident guard, not a sandbox.
- **Critical**: additionally a desktop alarm to the operator. Running jobs and
  their stacks still keep running; only the operator can make an exception.
- A measured fall that would reach the critical threshold within the
  projection window raises the stage by one at once.
- Caches together stay under their budget; the least recently used go first.

`watch.py status` shows the stage computed from the live free space and the
stored samples, and the age of the stored measurement.

An unusable config (broken JSON, wrong types, a regex refusing a light
probe such as `grep` or freeing a heavy one such as `make swarm-deploy`, a
dangling link, a directory) makes the hooks, admit, status and the queue
warn and use `config.default.json`, which the install writes when no config
exists; without that file every command, teardown included, is refused.
The probes are samples, so a pattern hitting only other commands passes. A
package script is read from the nearest package.json, a named workspace
only from a folder of that name. The light-run check misses
`sys.path.insert` in a conftest, editable installs without pytest
`pythonpath`, browser libraries outside its list and generic third-party
fixtures such as pytest-selenium's `driver`, browsers started by a
subprocess, and `git bisect run` or a suite script behind `bash`.
