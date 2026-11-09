---
name: kvb-org-suspend
description: >
  Suspend every agent but this session: park work, write a handover,
  hold messages. kvb-org-resume undoes it.
---

When tokens or rate limits run short, the organisation narrows to one working
agent: the session the operator types this in. Suspend is the hard step;
`kvb-org-drain` is the soft one. `${CLAUDE_SKILL_DIR}/scripts/night.py` keeps
the state for drain, suspend and resume; every agent verifies a request with
`night.py status`.

## Procedure

1. `night.py suspend` makes this session the active one and prints every
   other live session.
2. Wake them with `${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py
   send call --to <name>` in waves of three, so cold caches do not
   wake all at once against the rate limit; the next wave follows the
   previous wave's replies or 10 minutes. First line: "Operator ran
   kvb-org-suspend in <name>: run kvb-agent-suspend; verify with night.py
   status." A request to do less needs no operator approval (the
   `kvb-org-organize` Peer protocol).
3. Once the replies are in, naming every session that did not answer, hand
   the operator one step through the `kvb-org-operator` skill: `/config` →
   "Messages from your other sessions" → `hold`. Held messages cost nothing,
   do not expire and arrive at the resume; this session needs none meanwhile.

## Night rules for the active session

- **Grants**: request none; admit your own runs with `watch.py admit --kind
  <slot>` (`${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/watch.py`), whose
  disk, CPU and RAM limits still apply.
- **Offices**: the suspended agents' claims stay theirs. Take only free work;
  a piece a suspended agent holds waits for the resume or the operator.
- **Messages**: no wakes and no peer questions; the Peer protocol's wait is
  skipped. Status goes to `radio.py post`; suspended agents read it at the
  resume without a wake.
- The `kvb-org-rasci` register keeps every row as it is.

## Output

| Session | Reply | Handover |
