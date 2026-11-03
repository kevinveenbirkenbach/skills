# Dream hints

Two hints point at the dream; neither is a trigger:

- `hooks/reminder.sh` tells each agent at most once every twelve hours,
  stamped per session in `~/.claude/.dream-stamps/`.
- The `kvb-dream-notify.timer` user timer shows a GNOME notification daily at
  17:00 local time, catching up once after a missed run.

On a hint, print it and continue with the actual request.
