# Dream hints

Two hints point at the dream; neither is a trigger, and both start off to
save tokens:

- `hooks/reminder.sh` tells each agent once every N hours (default 12),
  stamped per session in `~/.claude/.dream-stamps/`.
- The `kvb-dream-notify.timer` user timer shows a GNOME notification daily at
  the set times (default 17:00), catching up once after a missed run.

The operator switches and retimes both in the hub's Controls › Schedules tab,
or with `kvb-org-organize/scripts/schedules.py set dream|dream-popup`; the
`kvb-schedules` units apply a change within seconds.

On a hint, print it and continue with the actual request.
