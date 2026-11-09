---
name: kvb-org-drain
description: >
  Drain every agent but this session: finish its task, end its loops,
  start nothing new. kvb-org-resume undoes it.
---

The soft step before `kvb-org-suspend`: this session keeps working, every
other finishes what it is doing and then idles. The state lives in
`${CLAUDE_SKILL_DIR}/../kvb-org-suspend/scripts/night.py`.

1. `night.py drain` makes this session the active one and prints every
   other live session.
2. One `${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py send call
   --to <session>` per printed session, since each must act, first
   line:
   "Operator ran kvb-org-drain in <name>: run kvb-agent-drain; verify with
   night.py status." A request to do less needs no operator approval (the
   `kvb-org-organize` Peer protocol).
3. Collect the one-line replies, which arrive by radio; never ask a silent
   session again. The night rules of `kvb-org-suspend` apply to this session
   too, and the `kvb-org-rasci` register keeps every row as it is.

## Output

| Session | Reply | Still running |
