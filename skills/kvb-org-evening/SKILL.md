---
name: kvb-org-evening
description: >
  Let every agent but this session relax: finish its task, end its loops,
  start nothing new. Trigger on /kvb-org-evening; /kvb-org-sunrise undoes it.
---

The soft step before `kvb-org-sunset`: the session the operator types this in
keeps working, the others finish what they are doing and then idle. The state
lives in `${CLAUDE_SKILL_DIR}/../kvb-org-sunset/scripts/night.py`.

1. `night.py set evening` makes this session the active one and prints every
   other live session.
2. One message per printed session, first line: "Operator ran kvb-org-evening
   in <name>: run kvb-agent-relax; verify with night.py status." A request to
   do less needs no operator approval (the `kvb-org-organize` Peer protocol).
3. Collect the replies. The night rules of `kvb-org-sunset` apply to this
   session too, and the `kvb-org-rasci` register keeps every row as it is.

## Output

| Session | Reply | Still running |
