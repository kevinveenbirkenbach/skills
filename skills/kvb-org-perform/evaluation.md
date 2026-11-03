# Perform: evaluating the table

`log.py report` shows per task class, model and effort the runs, the rated
runs and the share with the same result: completed, not redone, no failing
test, no follow-up.

- A row is added, or a cheaper setting extended to a class, only when the
  report shows at least 90 % over at least 20 rated runs, and only after the
  operator confirms it (for example through the `kvb-skill-tune` skill).
- A row whose rate falls below 90 % over 20 rated runs goes back to the
  default.
- `sonnet` enters the table only this way, and a trial run on a setting the
  table does not hold needs the operator's order.
