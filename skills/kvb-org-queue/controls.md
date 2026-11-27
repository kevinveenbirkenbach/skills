# Queue controls

The operator steers the queue from the hub's Controls tab Queue; agents never
run these commands.

## Start now

`queue.py override <id>` marks a waiting job. Its next poll grants it ahead
of rank, past the utilization band, slot limits, reservations and `after` waits,
while the live guard (`load_limits` CPU and RAM), the memory stage, radio
silence, the disk stage and floor and a running job of its worktree, stack
or slot allow; otherwise its reason starts with `override held by`. Its
history row records `override: true`. An unknown or running id exits 2.

## Learnings and settings

`queue.py learned --json` prints per kind the runs, shares, slot limit and
caps, per signature the learned values, the settings and the last 20 history
rows; it writes nothing.

`queue.py config set <key> <value>` changes one of `budget_percent.ram|cpu`,
`load_limits.cpu_percent|mem_percent|sample_seconds|band_low|band_high`
(band_low below band_high),
`slot_limits.<kind>` and `ram_cap_percent.<kind>` (a kind of
`slot_need_gb`). A bad value exits 2 and leaves the file byte-identical; a
good one rewrites the file atomically, every other key kept.

## Hub path

The hub stages the changes and one passkey signs the batch; the host runner
(`--queue`) runs each as `queue.py <argv>` and refuses every other argv. The
hub reads the config through a read-only mount and never writes it.
