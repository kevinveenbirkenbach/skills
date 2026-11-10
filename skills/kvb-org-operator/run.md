# operator.py run

Per step `run` shows directory, command, reason, check and a preview of the
change (commits and diffstat to push, files an install changes, what a
removal deletes, the repository state), and runs the command only on `y`;
`d` shows the full diff, `s` skips, `c` cancels with a reason the operator
must give (empty goes back), `q` stops. Nothing answers for the operator.

- **Cancel**: sets the row `stopped` with the reason under `cancelled` and
  posts "Operator cancelled operator/<slug> (...): <reason>" to every agent
  holding A. That agent treats it as the operator's rejection of exactly
  that step.
- **Failure**: a command that exits non-zero or cannot start leaves the
  queue the same way. The row is set `stopped` with the exit under
  `failed` and posted to every agent holding A with the request to queue
  the corrected command. `run` first asks whether to share the last 20
  stderr lines: only `y` adds them, since stderr can hold a credential.
  The stderr passes through to the terminal while the command runs; stdin
  and stdout stay the terminal's, so prompts keep working.
- **Interrupt**: exit 130 or a signal is the operator's own abort; the row
  stays open and nothing is posted.
- **Queue**: a heavy command can be held in `queue.py`; on the grant `run`
  asks again. Exit 75 from a held step means nothing ran, never a failure.

`add` under the same slug reopens the row and clears `cancelled` and
`failed`.
