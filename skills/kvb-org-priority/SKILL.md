---
name: kvb-org-priority
description: >
  Let the operator reorder the agents; it breaks ties of grants and equal task
  priority. Trigger on "prioritaet", "reihenfolge der agents".
---

The agent order is separate from task priority: it lies in
`agent-order.json` beside the `kvb-org-rasci` register, writes no `--prio`
pin and only breaks ties of equal task rank, also among `kvb-org-queue`
grants. The script is `${CLAUDE_SKILL_DIR}/../kvb-org-rasci/scripts/rasci.py`.

```bash
rasci.py agents
rasci.py agents order "<agent>,<agent>,..."
```

## Step 1: current order

`rasci.py agents` prints one line per agent with open tasks or an office, in
stored order, then register rank: number, agent, task count, tasks. Show it as a table with each agent's status and OKR from
`rasci.py show --wide`.

## Step 2: selection

One `AskUserQuestion`, `multiSelect: false`, the order of each option in its
`preview`:

- **Keep the current order**: nothing changes.
- **Suggested order**, at most two, each with its reason in the
  description: hotfix lines of the default branch first, then by WSJF; or
  blocked agents' unblockers first.
- The operator's own order arrives through `Other`, as agent names or the
  numbers of step 1 (map them to names), comma-separated.

An agent left out of the chosen order follows the listed ones in register
rank; say so in the question.

## Step 3: apply

`rasci.py agents order "<A>,<B>,..."` stores the order and touches no task
row. Show `rasci.py agents` again, then post the new order for the
resource chair of the `kvb-org-organize` skill and every reordered agent as
one `${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post "<text>"`,
not as wakes.

## Rules

- Never reorder without the operator's pick; a suggestion is not a decision.
- A name the register does not know stops the step with the list of known
  agents; never guess the closest one.