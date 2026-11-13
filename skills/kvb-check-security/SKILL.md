---
name: kvb-check-security
description: >
  MEDUSA security scan of a repository, working tree or secret stores:
  vetting a repo, leaked secrets in chat or shell history. Defensive only.
---

MEDUSA is a defensive AI-first security scanner (40,000+ patterns: CVEs, prompt injection, MCP tool poisoning, leaked secrets).

## Setup

Check availability with `medusa --version`.
The skills repository's `make install` installs it with pipx; if it is still missing, `pipx install medusa-security` is the operator's step.

## Commands

| Task | Command |
| --- | --- |
| Scan the current project | `medusa scan .` |
| Vet a remote repo BEFORE cloning (supply chain, poisoned `.claude/` hooks, permissions, skills) | `medusa scan --git <url-or-org/repo>` |
| Find leaked API keys in AI chat + shell history | `medusa secrets scan` |
| Scan one exported file | `medusa secrets scan --path <file>` |

## Security value of a change

The 🛡️ value of the `kvb-check-score` block:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/security.py --repo <root> --base <ref>
```

It scans the files changed since `<ref>`, untracked ones included, once and
prints one line: 100 % is safe, each critical, high, medium and low finding
costs 50, 25, 10 and 2. Pass the value as `--security` and the critical count
(`--json`) as `--critical` to `score.py`. A complete run is cached.

- Exit 0: 100 %. Exit 3: below 100 without a critical; the score gate asks
  the operator. Exit 1: a critical; the gate forbids the commit. Exit 2: usage.
- A `not covered` list or exit 4: read `coverage.md` next to this file first.
- **Accepted false positives**: `security.py accept --repo <root> --rule <id>
  [--rule <id> ...] --path <path> --sha1 <sha1> --line <n> --reason "<one line>"`
  (values from `--json`) keeps a finding out of the score until its line or
  neighbourhood changes; `--line` is required when the text recurs. Accept
  only after `kvb-think-criticize` judged it a false positive or by design;
  name each acceptance in the commit message.

## Rules

- Run scans read-only; never pass `--reveal` and never run `medusa secrets purge` unless the user explicitly asks for it.
- Summarize findings by severity with file/line references; do not paste secret values into the conversation, even redacted ones.
- Treat findings as signals for review, not verdicts; confirm true positives in the code before proposing fixes.
- Vet third-party agent repos (`medusa scan --git`) before recommending the user clone or install them.
