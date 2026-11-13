# operator.py run

Per step `run` shows directory, command, reason, check and a preview of the
change (commits and diffstat to push, files an install changes, what a
removal deletes, the repository state), and runs the command only on `y`;
`d` shows the full diff, `s` skips, `c` cancels with a reason the operator
must give (empty goes back), `q` stops. Nothing answers for the operator.

Every outcome below goes to each agent holding A as a radio call to the
name and session `add` stored (a row without one: the name), whatever its
`radio.py feedback` channel; the call names slug, outcome and exit, never
command output. A row that closes outside `run` calls the same way, once:
its check passing in the sweep of `list`, `run` or `granted` ("... done:
check passed (<check>)"), or `done` ("... marked done by <name>").

- **Done**: exit 0 sets the row `done` once its check passes and sends
  "Operator ran operator/<slug>: done, exit 0"; a check not passing yet
  keeps the row open and says so.
- **Cancel**: sets the row `stopped` with the reason under `cancelled` and
  sends "Operator cancelled operator/<slug> (...): <reason>". That agent
  treats it as the operator's rejection of exactly that step.
- **Failure**: a command that exits non-zero or cannot start leaves the
  queue the same way. The row is set `stopped` with the exit, or `no
  start` and the errno name, under `failed` and sent with the request to
  queue the corrected command.
  `run` first asks whether to share the last 20 stderr lines: only `y`
  stores them under the row's `failed.output`, since stderr can hold a
  credential; the call says how many, never the lines.
  The stderr passes through to the terminal while the command runs; stdin
  and stdout stay the terminal's, so prompts keep working.
- **Interrupt**: exit 130 or a signal is the operator's own abort; the row
  stays open and nothing is sent.
- **Queue**: a heavy command can be held in `queue.py`; on the grant `run`
  asks again. Exit 75 from a held step means nothing ran, never a failure.

`add` under the same slug reopens the row and clears `cancelled` and
`failed`.

The hub's runner reports through `ran` and `failed`, as the same calls:
exit 0 closes the row from any status but done, whatever its check; exit
130 and signals count as failures. Any agent of the same user can forge `ran`, `failed` or
`done`: the register and the radio are writable by every agent already.
