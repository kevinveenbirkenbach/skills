# Queue history and learning

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
