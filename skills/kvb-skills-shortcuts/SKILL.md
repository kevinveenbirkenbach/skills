---
name: kvb-skills-shortcuts
description: >
  Operator conversation shortcuts. Trigger when the message is exactly one of
  these tokens, optionally with arguments: sobu, soco, socobu, socon, sona,
  sote. Expand it and act on the expanded instruction.
---

When an operator message is one of the shortcuts below, expand it to the meaning and act on it.

| Shortcut | Meaning |
| --- | --- |
| `sobu` | Stage next bundle: stage the next logical bundle of verified changes, explain what it does, and list what still remains uncommitted. |
| `soco` | Commit: commit the currently staged changes (pre-commit hooks run). |
| `socobu` | Commit no-verify, then stage next bundle: run `socon` followed by `sobu`. |
| `socon` | Commit no-verify: commit the currently staged changes with `--no-verify`. |
| `sona` | New alias: add the shortcut the operator states to the appropriate table, keeping it sorted. |
| `sote` | Run `make test`. |
