---
name: kvb-check-security
description: >
  Run the MEDUSA scanner on a repository, working tree or secret stores:
  security scans, vetting a repo, leaked secrets in chat or shell history, or
  /kvb-check-security. Defensive only.
---

MEDUSA is a defensive AI-first security scanner (40,000+ patterns: CVEs, prompt injection, MCP tool poisoning, leaked secrets).

## Setup

Check availability with `medusa --version`.
If missing, install it with `pipx install medusa-security` (fallback: `pip install --user medusa-security`).

## Commands

| Task | Command |
| --- | --- |
| Scan the current project | `medusa scan .` |
| Vet a remote repo BEFORE cloning (supply chain, poisoned `.claude/` hooks, permissions, skills) | `medusa scan --git <url-or-org/repo>` |
| Find leaked API keys in AI chat + shell history | `medusa secrets scan` |
| Scan one exported file | `medusa secrets scan --path <file>` |

## Rules

- Run scans read-only; never pass `--reveal` and never run `medusa secrets purge` unless the user explicitly asks for it.
- Summarize findings by severity with file/line references; do not paste secret values into the conversation, even redacted ones.
- Treat findings as signals for review, not verdicts; confirm true positives in the code before proposing fixes.
- Vet third-party agent repos (`medusa scan --git`) before recommending the user clone or install them.
