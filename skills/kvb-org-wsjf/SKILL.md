---
name: kvb-org-wsjf
description: >
  WSJF priority from Fibonacci estimates. Trigger on /kvb-org-wsjf, "wsjf",
  "priorisieren".
---

Weighted Shortest Job First ranks the tasks of the `kvb-org-rasci` register
by cost of delay over job size: here business value over complexity, each the
median of Fibonacci estimates (1, 2, 3, 5, 8, 13, 21, 34, 55, 89). The
estimates live in the register's table; `wsjf` is its WSJF view, one row per
task with its OKR and the task id the register uses, and the register's Prio
column is this rank. The script is
`${CLAUDE_SKILL_DIR}/../kvb-org-rasci/scripts/rasci.py`.

```bash
rasci.py estimate <task> "<party>" --value <fib> --complexity <fib>
rasci.py estimate <task> "<party>" --drop
rasci.py wsjf [--all]
```

## Procedure

1. **The chair asks.** For every new task, and when its objective or a key
   result changes, the resource chair of the `kvb-org-organize` skill asks
   its subordinates (the task's worker and R, the representatives of the
   lines it touches) for one Fibonacci estimate each of business value and
   complexity, one message per agent.
2. **Record each answer** under the party that gave it; a new estimate
   replaces the old one. An agent may record its own.
3. **Rank**: WSJF = median business value / median complexity, highest
   first. An operator's pin (`rasci.py set <task> --prio <n>`) outranks every
   score; unestimated tasks come last and are named under `unestimated:`.
4. **Grant in rank order**: the chair hands out capacity by this rank, except
   that a hotfix gate (a branch from the default branch that fixes it) takes
   the next free gate or test slot before every ranked task; a running gate
   is never cut short for it.

## Rules

- Estimate relative to the other open tasks, never in hours.
- Never invent an estimate for a party that did not answer; a task without
  one stays unestimated.
