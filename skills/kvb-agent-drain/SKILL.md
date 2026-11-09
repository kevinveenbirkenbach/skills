---
name: kvb-agent-drain
description: >
  Drain this agent on kvb-org-drain: finish its task, end its loops, start
  nothing new.
---

Verify first: `${CLAUDE_SKILL_DIR}/../kvb-org-suspend/scripts/night.py status`
prints `you: drain`. On `you: active` or `mode: day` do nothing and say so.
The request asks for less, so it needs no operator approval.

Follow steps 2 to 4 of the `kvb-agent-suspend` skill (start nothing, end your
loops, write the handover), with two differences: finish the current task
instead of parking it, and keep answering the operator. Reply through the
radio, not a wake: `${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py
post --to <sender> "drained: <what still runs>"`. Resuming is the
`kvb-agent-resume` skill.
