# Queue history and learning

Every finished job appends a row (signature such as `<repo>: make <target>`,
kind, minutes, disk, RAM and CPU) to `queue-history.jsonl`; the
`kvb-org-organize` watch hook keeps it across reboots. The row of a run
hold ended for standing still (exit 124, a `hung` probe) teaches nothing.

From the last 30 days, once 5 runs exist:

- per job, the disk need is p90 disk taken plus 1 GB over the runs of its
  signature and kind; until 5 exist there, the largest such need its
  signature and the command's older signature learned over every kind;
- per kind, the reported slot limit is how many p90 RAM and median CPU
  shares fit between the median load at the grant and `load_limits`, at
  least 1; it blocks nothing, the utilization band admits;
- per job, the footprint is its signature's share over the runs of its
  kind, the p95 of the peak RAM and CPU taken times its margin; until 5
  exist there, the largest of its kind's share and what its signature and
  the command's older signature learned over every kind;
- per signature, the margin starts at 1.0, grows by the overshoot ratio
  after a run that took more than its grant booked (`predicted` on the
  row) and shrinks by 0.05 after one that took less, always 1.0 to 2.0.

A job of a kind outside `light_kinds` never books less than the queue before
the per-kind learning: at least the share its older signature learned over
every kind, else its kind's, and at least that signature's disk need once
learned. Only light kinds learn lower.

A pytest or unittest signature counts what the run names and its xdist
workers (`pytest files=1`, `pytest paths=2 workers=auto`), so one test file
never learns from a suite; the older signature is `<repo>: <command
signature>`, which older rows carry. A granted job keeps the footprint it
was granted on.

Until then the seeds hold: `slot_need_gb[kind]` for disk, the whole
`budget_percent` as footprint.
The optional `slot_limits {kind: N}` is the operator's hard cap per kind.
The optional `ram_cap_percent {kind: percent}` caps the RAM share a job of
that kind books, its footprint and its ceiling, while the learned shares and
the history rows stay raw; keep it truthful by limiting the job's own memory
to that share, such as a container memory limit. A waiting hold keeps the
code it loaded: hold it again after an install so it books with the cap.
