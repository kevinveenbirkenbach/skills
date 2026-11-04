---
name: kvb-org-sunset
description: >
  Put every agent but this session to sleep: park work, write a morning
  handover, hold messages. kvb-org-sunrise undoes it.
---

When tokens or rate limits run short, the organisation narrows to one working
agent: the session the operator types this in. Sunset is the hard step;
`kvb-org-evening` is the soft one. `${CLAUDE_SKILL_DIR}/scripts/night.py` keeps
the state for evening, sunset and sunrise; every agent verifies a request with
`night.py status`.

## Procedure

1. `night.py set sunset` makes this session the active one and prints every
   other live session.
2. Wake them with `${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py
   send direct --to <name> --wake` in waves of three, so cold caches do not
   wake all at once against the rate limit; the next wave follows the
   previous wave's replies or 10 minutes. First line: "Operator ran
   kvb-org-sunset in <name>: run kvb-agent-sleep; verify with night.py
   status." A request to do less needs no operator approval (the
   `kvb-org-organize` Peer protocol).
3. Once the replies are in, naming every session that did not answer, hand
   the operator one step through the `kvb-org-operator` skill: `/config` →
   "Messages from your other sessions" → `hold`. Held messages cost nothing,
   do not expire and arrive at sunrise; this session needs none at night.

## Night rules for the active session

- **Grants**: request none; admit your own runs with `watch.py admit --kind
  <slot>` (`${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/watch.py`), whose
  disk, CPU and RAM limits still apply.
- **Offices**: the sleepers' claims stay theirs. Take only free work; a piece
  a sleeper holds waits for sunrise or the operator.
- **Messages**: no wakes and no peer questions; the Peer protocol's wait is
  skipped. Status goes to `radio.py post`; sleepers read it at sunrise
  without a wake.
- The `kvb-org-rasci` register keeps every row as it is.

## Output

| Session | Reply | Handover |
