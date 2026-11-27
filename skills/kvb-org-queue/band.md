# Utilization band, limits file and self-tuning

## Utilization band

`load_limits.band_low` and `band_high` (default 70 and 90) steer the
queue's concurrency: while a queue job runs, a job starts only while
measured CPU and RAM (plus young jobs' ramp and this pass's grants) lie
below `band_low` (`load 72 % RAM >= 70 % band`) and stay at or below
`band_high` with its learned footprint (`would reach 93 % RAM > 90 %`);
an unlearned kind books `budget_percent`. Behind a reserving head a job
starts only while load plus the head's and its own footprint stays within
`band_high`, its last capped slot included; else it waits `reserved for
<head>`, and `drained for <head>` only when the head cannot fit even alone.
Keep the live guard
`mem_percent` above `band_high`, or it holds jobs first.

## Limits file

`<council root>/limits.json` (the `AGENTS_COUNCIL_ROOT` directory) is the
one source of the limits for queue, watch and hub:

```json
{"cpu":  {"lower": 70, "upper": 90, "stop": 95, "mayday": 99},
 "ram":  {"lower": 70, "upper": 85, "stop": 92, "mayday": 97},
 "swap": {"lower": 20, "upper": 60, "stop": 90, "mayday": 97},
 "disk": {"lower": 70, "upper": 85, "stop": 95, "mayday": 98},
 "psi":  {"lower": 1, "upper": 10, "stop": 30, "mayday": 60}}
```

All five metrics with all four levels, each a percent 0 to 100 (CPU busy,
RAM, swap and disk used, memory PSI some avg10), lower < upper < stop <
mayday per metric. Readers: queue band = cpu/ram lower and upper, live
guard = their stop; watch memory warn = ram/swap/psi upper, stop = their
stop; disk warn, stop (the queue floor) and critical = disk upper, stop and
mayday. A refused file keeps `limits.last.json`, the last valid copy, in
force; without the file the config applies (`kvb-org-organize/scripts/limits.py`).

## Self-tuning target

Each poll steps a target per CPU and RAM in `limits-target.json`, starting
at upper: +2 while the 10-minute average lies below lower and PSI is calm
(below psi lower, else 1), down to the middle of lower and itself at once
when load passes upper, PSI rises or swap goes out. A job fits only while
load plus its footprint stays within the target (`would reach 88 % RAM >
target 84.0 %`); while a job runs, one grant per `sample_seconds`
(`settles: ...`). Footprints are the command's RAM p95 and CPU median,
times its learned margin (`learning.md`). The `list` header names target,
band and limits source.
