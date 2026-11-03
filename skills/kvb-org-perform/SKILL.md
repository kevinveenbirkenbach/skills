---
name: kvb-org-perform
description: >
  Pick `model` and `effort` per subagent from a fixed table, cheaper only at
  90 % confidence of an equal result. Apply AUTOMATICALLY before every Agent
  tool call.
---

A subagent runs on the main model and effort unless the spawn names others.
Set `model` and `effort` only for a task that clearly matches a row below, at
least 90 % sure the cheaper setting gives the default's result: no lost
findings, no rework. Cost counts per finished task, retries included.
Otherwise set neither.

## Table

| Task class | Subagent's task | `model` | `effort` | Evidence |
| --- | --- | --- | --- | --- |
| `lookup` | Read-only: find files, symbols or call sites, grep, list, read and quote, pull a log line or field, summarise a given text without judging it | `haiku` | `low` | Haiku 5.5 costs 1/40 of Opus 5.5 per token and is the speed tier; Anthropic names Haiku at low effort for simple, speed-critical and reading-heavy worker tasks; Explore and the cavecrew investigator already run on it |
| `mechanical-edit` | An edit the brief fully specifies (exact old and new text, a rename, deleting listed lines) in one or two files | `haiku` | `low` | nothing is left to decide, and the parent checks the diff |
| `judgement` | Everything else: root cause, skeptic or dialectic antithesis, review, security or legal checks, design, new or multi-file code, writing tests, performance work | omit | omit | no evidence at 90 % that a cheaper setting gives the same result |

Prices per million tokens in and out (claude-api reference, cached
2026-10-06): Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20,
Fable 5.1 $10 / $50.

## Spawn

1. Pick the class; a task that mixes classes, or whose class you hesitate
   over, is `judgement`.
2. Start the brief with `task-class: <class>`; the spawn hook logs it with
   `model`, `effort` and the Agent `description`.
3. Set `model` and `effort` from the row; for `judgement` set neither.
4. Spawn as many agents as the stakes need: one, unless independent parts
   gain from running in parallel. The brief names the exact files, lines and
   claims to check and what is ruled out, and caps the answer (for example
   "at most 15 lines, file:line per finding").
5. Enter the spawn in the `kvb-org-rasci` register: the subagent as R and as
   `--worker "subagent <type> (<model>, <effort>)"` of the task it serves.

- An agent type whose definition sets its own model (Explore, Plan, the
  cavecrew agents) keeps it; never pass `model` or `effort` for it.
- Never pass `fable` or `opus`: neither is cheaper than the default.
- A Haiku agent that reports the task needs judgement, or returns an
  incomplete result, is not retried on Haiku: the default continues it.
- Never change the default itself (settings, `CLAUDE_CODE_SUBAGENT_MODEL`,
  agent definitions); this skill only chooses per call.

## Feedback

Once you have judged the result, rate it under the same Agent `description`:

```bash
${CLAUDE_SKILL_DIR}/scripts/log.py feedback --description "<description>" --completed yes|no --tests pass|fail|none --redo yes|no
```

`--redo yes` when the default had to redo or finish the work. When the
operator later asks a follow-up about that result or corrects it:

```bash
${CLAUDE_SKILL_DIR}/scripts/log.py followup --description "<description>" --text "<question or correction>"
```

All sessions share `~/.local/state/agents-council/subagent-model.jsonl`; a
sandbox that cannot write it gets the line printed as `pending:`, and the
PostToolUse hook stores it.

Read `evaluation.md` next to this file before reading `log.py report` or
changing a row of the table.
