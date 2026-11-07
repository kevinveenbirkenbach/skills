---
name: kvb-check-ansible
description: >
  Rank where an Ansible run spends its time from its log, profile the
  controller, bench per-task overhead. Trigger on a slow playbook or deploy.
---

Where an Ansible run spends its time: its log, a controller profile, a bench.
Report the script's lines with their log and range, never a guess. The
script and the bench are light runs (`watch.py admit --kind test-nostack` of
`kvb-org-organize`); a deploy to profile is heavy and goes through the
`kvb-org-queue` skill.

## 1. Pick the log

- The newest log of the current code; an older one may time a task since
  replaced.
- A log whose lines start with an ISO timestamp (GitHub Actions) times every
  task by wall clock. A local run needs
  `ANSIBLE_CALLBACKS_ENABLED=ansible.posix.profile_tasks`, streamed to a file.
- One deploy among several: bound it with `--from` and `--to`, line numbers
  from `grep -n 'PLAY \['`.

## 2. Rank

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/ansible_tasks.py gaps --log <log> --top 20
```

| Subcommand | Prints |
| --- | --- |
| `gaps` | wall seconds and count per task name, then `TOTAL` |
| `durations` | the same from `profile_tasks` `(h:mm:ss.sss)` lines |
| `kinds` | per kind (ran, skipped, included, other): count, sum, mean, buckets `<0.25` to `>=2` s |
| `kind --kind <kind>` | per task name, that kind only |
| `task --needle <text>` | every occurrence: start line, seconds, kind |

`kinds`, `kind` and `task` read wall gaps when a header carries a timestamp,
else `profile_tasks` lines; `--source wall|profile` forces one. A task runs
from its header to the next header or `PLAY RECAP`. `--json` prints JSON;
exit 2 means nothing measurable in the range.

Rank by sum, a name's cost times its count: 400 skips of 0.3 s outweigh one
60 s download.

## 3. Profile the controller

A skipped task does no work on any host; its time is controller overhead
(templating, variable merging, one worker fork per task). Profile only when
`kinds` shows it: a `skipped` mean of 0.1 s or more, or `skipped` and
`included` together holding 10 % of the sum or more.

```bash
ANSIBLE_PROFILE_DIR=<new dir> PYTHONPATH=${CLAUDE_SKILL_DIR}/scripts/profile ansible-playbook <the run's arguments>
python3 ${CLAUDE_SKILL_DIR}/scripts/ansible_tasks.py profile-report --dir <new dir> --top 30
```

- `sitecustomize.py` profiles only a process named `ansible-playbook`: the
  controller into `main-<pid>.prof`, each forked worker into
  `worker-<pid>.prof`; without `ANSIBLE_PROFILE_DIR` into
  `$TMPDIR/ansible-profile`.
- The report merges every file of the directory: a new one per run.
- `PYTHONPATH` must reach the controller's interpreter (virtualenv,
  container) and shadows a distribution's own `sitecustomize`.
- A profiled run is slower: compare profiles with profiles, never its wall
  clock with an unprofiled run.

## 4. Bench the per-task overhead

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/ansible_tasks.py bench-carrier --kb <size> --out <dir>/carrier.json
ANSIBLE_CALLBACKS_ENABLED=ansible.posix.profile_tasks ansible-playbook -i ${CLAUDE_SKILL_DIR}/bench/hosts.yml ${CLAUDE_SKILL_DIR}/bench/bench.yml -e bench_count=200 -e bench_carrier_file=<dir>/carrier.json > <dir>/bench-<size>.log 2>&1
python3 ${CLAUDE_SKILL_DIR}/scripts/ansible_tasks.py kinds --log <dir>/bench-<size>.log
```

Each item includes one skipped and one run `debug` task on localhost. Run
once without `bench_carrier_file` and once per `<size>` in KiB, up to the
run's biggest variable; the change of the `skipped` mean is that fact's cost
per task. Without `ansible.posix`, divide the wall-time difference of
`bench_count=0` and `bench_count=200` by 400.

## Report

Per finding: subcommand, log and range, its line as printed, and the saving
ceiling, count times the measured cost per task. Hand the ranking to the
`kvb-code-tune` loop.
