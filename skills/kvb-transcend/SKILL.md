---
name: kvb-transcend
description: >
  Run both transcend skills in one pass. Trigger on /kvb-transcend.
---

Collector for the `kvb-skills-transcend` and `kvb-code-transcend` skills, so
one harvest needs one round of questions. Its script finds the candidates and
remembers every decision, so a rescan offers only what is new or changed:

```bash
transcend.py scan --state <skills repo>/.state/transcend.json \
  --skills-repo <skills repo> --session-dir <own scratchpad> \
  --peers-root /tmp/claude-<uid> --home ~ [--json]
transcend.py mark --state <same> <path> carried|dropped|later
```

`${CLAUDE_SKILL_DIR}/scripts/transcend.py` scans three sources: the own
scratchpad, every peer session's scratchpad, and the agent homes
(`~/.claude`, `~/.agents`, `~/.codex`) for skills, commands, agents, hooks
and rules the skills repository does not ship. It keeps scripts, tests and
skills, and skips files named like secrets and files over 1 MB. Carried or
dropped candidates return only when their content changes; `later` returns
every time.

1. Scan, then classify each candidate by both skills' classify steps.
2. Consent: a peer's candidates go to that peer, one message listing them,
   and only what it releases stays; home candidates need the operator's yes.
3. One `kvb-think-listen` round and one confirmation for all candidates,
   grouped by target: the skills repository or the current repository. In
   the skills repository itself, scripts and skills go to
   `kvb-skills-transcend`, tests to `kvb-code-transcend`.
4. Hand each confirmed candidate to its skill's write step, then `mark` every
   offered candidate with its verdict.
5. One table: `| Candidate | Source | Target | Verdict |`.
