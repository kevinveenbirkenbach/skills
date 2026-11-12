# Queue history and learning

Every finished job appends a row (signature such as `<repo>: make <target>`,
kind, minutes, disk, RAM and CPU) to `queue-history.jsonl`; the
`kvb-org-organize` watch hook keeps it across reboots.

From the last 30 days, once 5 runs exist:

- per job, the disk need is p90 disk taken plus 1 GB over the runs of its
  signature and kind; until 5 exist there, the largest such need its
  signature and the command's older signature learned over every kind;
- per kind, the slot limit is how many p90 RAM and median CPU shares fit
  between the median load at the grant and `load_limits`, at least 1;
- per job, the footprint is its signature's share over the runs of its
  kind; until 5 exist there, the largest of its kind's share and what its
  signature and the command's older signature learned over every kind.

A job of a kind outside `light_kinds` never books less than the queue before
the per-kind learning: at least the share its older signature learned over
every kind, else its kind's, and at least that signature's disk need once
learned. Only light kinds learn lower.

A pytest or unittest signature counts what the run names and its xdist
workers (`pytest files=1`, `pytest paths=2 workers=auto`), so one test file
never learns from a suite; the older signature is `<repo>: <command
signature>`, which older rows carry. A granted job keeps the footprint it
was granted on.

Until then the seeds hold: `slot_need_gb[kind]` for disk, 1 slot per kind,
the whole budget as footprint.
The optional `slot_limits {kind: N}` only caps a limit from above.
