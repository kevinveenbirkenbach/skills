# Done checks

Choose the strongest check that proves the step done. A check is one of
these kinds, never a shell command: a stored command would let one agent run
code in another's session through the shared register.

| Kind | Done when |
| --- | --- |
| `pushed:<repo dir>` | `git rev-list --count @{u}..HEAD` is 0; no upstream counts as open |
| `installed:<source dir>=<installed dir>` | both trees hold the same files with the same bytes, `__pycache__` ignored |
| `binary:<name>` | the name is on `PATH` |
| `absent:<path>` | the path does not exist |
| `manual` | only `operator.py done <slug>` closes it, or `run` once the command exits 0 |
| `decision` | only `operator.py done <slug>` closes it; never in a block or `run` |

`manual` is the last resort for a runnable command such as a reboot. Every
non-`decision` row's `--command` must run as typed in the operator's shell,
because `run` executes it on `y`; prose there ("Rotate leaked credentials")
is a defect. A decision, a browser or hardware step, or anything else
without a shell command takes `decision`, its question or instruction as
`--command`. Other kinds, relative paths and shell
metacharacters exit 2.
