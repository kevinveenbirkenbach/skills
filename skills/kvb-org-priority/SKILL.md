---
name: kvb-org-priority
description: >
  Let the operator reorder the agents' priority from a selection; pins their
  tasks in that order. Trigger on /kvb-org-priority, "prioritaet", "reihenfolge
  der agents".
---

The operator's order of the agents outranks every WSJF score. It is written
as `--prio` pins into the `kvb-org-rasci` register, so the chair's grants of
the `kvb-org-wsjf` skill follow it. The script is
`${CLAUDE_SKILL_DIR}/../kvb-org-rasci/scripts/rasci.py`.

```bash
rasci.py agents
rasci.py order "<agent>,<agent>,..."
```

## Step 1: current order

`rasci.py agents` prints one line per agent with open tasks, in the
register's rank: number, agent, task count, tasks. Show it as a table with
each agent's status and OKR from `rasci.py show`.

## Step 2: selection

One `AskUserQuestion`, `multiSelect: false`, the order of each option in its
`preview`:

- **Keep the current order**: nothing changes.
- **Suggested order**, at most two, each with its reason in the
  description: hotfix lines of the default branch first, then by WSJF; or
  blocked agents' unblockers first.
- The operator's own order arrives through `Other`, as agent names or the
  numbers of step 1 (map them to names), comma-separated.

An agent left out of the chosen order loses its pins and ranks by WSJF after
the listed ones; say so in the question.

## Step 3: apply

`rasci.py order "<A>,<B>,..."` pins the listed agents' tasks 1..n in that
order, keeping each agent's own task order. It writes other sessions' rows:
the operator decides priority, so this is the one exception to "write only
your own rows". Show `rasci.py agents` again, then tell the resource chair
of the `kvb-org-organize` skill and every reordered agent their new rank, one
message each.

## Rules

- Never reorder without the operator's pick; a suggestion is not a decision.
- A name the register does not know stops the step with the list of known
  agents; never guess the closest one.
