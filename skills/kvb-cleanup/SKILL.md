---
name: kvb-cleanup
description: >
  Free disk space agents filled in /tmp, Docker and agent dirs; delete only
  operator picks. Trigger on "aufräumen", "bereinigen",
  "platte voll", "no space left on device".
---

Delete only this run's operator picks; asking, inventory and proposal change
nothing. Never invent a size or a peer's answer: unmeasured is `unknown`.

## Step 0: the chair

Shared resources belong to the `kvb-org-organize` chair; its watch
runs the configured low-risk cleanup. Another session chairs: send it the
request and stop, or, ordered here by the operator, first
`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post --to <chair>
"<plan>"`.

## Steps 1 to 4: inventory, owners, classes, proposal

Read `plan.md` here and follow it to its `Execute` pick.

## Step 5: execute

After `Execute`, read `execute.md` first.

## Step 6: report

`df -h` and `docker system df` before and after, freed size per area, skipped
or failed items with reasons. `radio.py post --to <peer>` each
answering peer the removed items near its own.
