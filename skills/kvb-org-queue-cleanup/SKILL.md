---
name: kvb-org-queue-cleanup
description: >
  Twice daily, delete dead queue jobs.
---

`${CLAUDE_SKILL_DIR}/scripts/cleanup.py` runs one cleanup round of the
`kvb-org-queue`, accountable to the top chair (council office `chair`);
without a live chair it deletes nothing.

## Round

1. A job (waiting or running) is dead only when no line of `/proc/locks`,
   of any type, pid or waiting state, names its hold's lock file
   `holds/<tag>.lock` and a flock on that file would not block, or when the
   file is gone. Whoever owns a job, and whatever its queue entry says, a
   living holder keeps it. Nothing is dead while `/proc/locks` is
   unreadable, unparsable or misses the round's own flock on `holds/`, nor
   is a job whose lock file is unreadable, no regular file, or changed
   after its hold created it. Malformed entries stay.
2. Without a dead job the round sends nothing. Else a pan-pan names the dead
   jobs; a 15 min window runs on both the wall and the monotonic clock.
3. A security names the jobs still dead and every job left alone with "held
   by a living process, not deleted"; another 15 min window runs.
4. Each job still dead under the same id and lock tag, judged again under
   the queue lock, leaves the queue. Nothing is signalled, no stop is
   written.
5. The chair gets the counts by post; the `kvb-org-rasci` register records
   the round as task `queue-cleanup`.

The round keeps its state in
`~/.local/state/agents-council/queue-cleanup.json`, which only the host
writes. Radio silence on any poll, a stall above 3 minutes, a newer round,
or a chair gone stale before the delete ends the round at once, deletes
nothing and records it `stopped`; so does any other error, with one post to
the chair.

`cleanup.py status` shows the open round's jobs: delete, held or unclear.
There is nothing to answer.

## Triggers

- `kvb-org-queue-cleanup.timer`, which `make install` enables, at 00:00 and
  12:00 host local time, without catch-up.
- `kvb-org-queue-cleanup.path` on `cleanup.py request`, which `kvb-cleanup`
  runs; `request` exits 2 without the installed path unit, while a round
  runs and for 30 minutes after one ended.
- Another interval: `systemctl --user edit kvb-org-queue-cleanup.timer`, a
  `[Timer]` drop-in of an empty `OnCalendar=`, then `OnCalendar=<spec>`.
- `cleanup.py run --window <seconds>` refuses inside an agent session, below
  900 s and without write access to the host state; the service passes 900.

## Limits

- A lock file removed while its hold lives reads as gone, so its job is
  deleted; `queue.py` itself prunes such an entry on its next poll.
- Started outside the initial PID namespace, the round misses POSIX locks of
  processes it cannot see; the service runs in it.
- The alarms name at most 6 ids per list; `status` lists all.
- The 30-minute spacing binds `cleanup.py request` only; a line appended to
  the request file otherwise starts a round once none runs.
