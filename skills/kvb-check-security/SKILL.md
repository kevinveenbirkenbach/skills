---
name: kvb-check-security
description: >
  Run the MEDUSA scanner on a repository, working tree or secret stores:
  security scans, vetting a repo, leaked secrets in chat or shell history.
  Defensive only.
---

MEDUSA is a defensive AI-first security scanner (40,000+ patterns: CVEs, prompt injection, MCP tool poisoning, leaked secrets).

## Setup

Check availability with `medusa --version`.
The skills repository's `make install` installs it with pipx; if it is still missing, `pipx install medusa-security` (fallback: `pip install --user medusa-security`) is the operator's step.

## Commands

| Task | Command |
| --- | --- |
| Scan the current project | `medusa scan .` |
| Vet a remote repo BEFORE cloning (supply chain, poisoned `.claude/` hooks, permissions, skills) | `medusa scan --git <url-or-org/repo>` |
| Find leaked API keys in AI chat + shell history | `medusa secrets scan` |
| Scan one exported file | `medusa secrets scan --path <file>` |

## Security value of a change

The 🛡️ value of the `kvb-check-score` block, 100 % meaning safe:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/security.py --repo <root> --base <ref>
```

It copies the files changed since `<ref>`, untracked ones included and
symlinks left out, to a temporary tree, scans it once with
`medusa scan <tree> --format json -o <dir> --no-cache` and prints one line:
`🛡️ security <n> % (medusa: <k> findings in <m> files: <severity> <path>:<line>, ...)`.
`<n>` is 100 minus 50 per critical, 25 per high, 10 per medium and 2 per low
finding, at least 0. It shows locations and counts only, never a matched
value. Pass `<n>` as `--security` and the critical count as `--critical`
(`--json` holds it) to `score.py`.

- Exit 0: 100 %. Exit 3: below 100 without a critical finding; the score
  gate asks the operator. Exit 1: a critical finding; the score gate forbids
  the commit.
- Exit 4: medusa is missing or its report unreadable. Review trust
  boundaries, secrets and injection in the diff by hand, then pass
  `--security '~<n>'` (quoted: zsh expands a bare `~100` as a user's home) and the critical findings you found as `--critical`.
- Exit 2: usage error.
- **Accepted false positives**: `security.py accept --repo <root> --rule
  <id> [--rule <id> ...] --path <path> --sha1 <sha1> --reason "<one line>"`
  (from `--json`) appends a row per rule to the council root, which the
  `kvb-org-organize` watch hook mirrors to `~/.local/state/agents-council/`.
  A match leaves the score as `<a> accepted` until the line changes. Accept
  only after `kvb-think-criticize` judged it a false positive or by design;
  name each acceptance in the commit message.

## Rules

- Run scans read-only; never pass `--reveal` and never run `medusa secrets purge` unless the user explicitly asks for it.
- Summarize findings by severity with file/line references; do not paste secret values into the conversation, even redacted ones.
- Treat findings as signals for review, not verdicts; confirm true positives in the code before proposing fixes.
- Vet third-party agent repos (`medusa scan --git`) before recommending the user clone or install them.
