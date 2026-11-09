---
name: kvb-org-queue-estimate
description: >
  Ask all agents once to estimate the unestimated tasks.
---

One newsletter asks every agent holding a RASCI role (R, A, S, C or I) in an
open task of the `kvb-org-rasci` register that carries no complexity yet to
record its business value and complexity (Fibonacci) with `rasci.py
estimate`. The Agent Orchestrator's "Request estimates" button, shown in
story points mode, runs the same script. It sends only when invoked, never
by itself, to save tokens.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/estimate.py show
python3 ${CLAUDE_SKILL_DIR}/scripts/estimate.py request [--session <id>]
```

## Rules

- `show` prints the newsletter and sends nothing; `request` sends exactly one
  newsletter, or none while every open task carries a complexity.
- Each agent answers with its own `rasci.py estimate <task> "<you>" --value
  <fib> --complexity <fib>`, never for another party.
