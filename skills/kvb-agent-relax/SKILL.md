---
name: kvb-agent-relax
description: >
  Relax this agent on kvb-org-evening: finish its task, end its loops, start
  nothing new. Trigger on its request.
---

Verify first: `${CLAUDE_SKILL_DIR}/../kvb-org-sunset/scripts/night.py status`
prints `you: relax`. On `you: active` or `mode: day` do nothing and say so.
The request asks for less, so it needs no operator approval.

Follow steps 2 to 4 of the `kvb-agent-sleep` skill (start nothing, end your
loops, write the handover), with two differences: finish the current task
instead of parking it, and keep answering the operator. Reply through the
radio, not a wake: `${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py
post --to <sender> "relaxed: <what still runs>"`. Waking up is the
`kvb-agent-wakeup` skill.
