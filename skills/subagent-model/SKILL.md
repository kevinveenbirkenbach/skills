---
name: subagent-model
description: >
  Pick `model` and `effort` per subagent from a fixed table: cheaper only on a
  clear match at 90 % that the result equals the default's; log spawns and
  quality. Apply AUTOMATICALLY before every Agent tool call.
---

A subagent runs on the main model and effort unless the spawn names others.
Set `model` and `effort` on an Agent call only when the task clearly matches a
row below and you are at least 90 % sure the cheaper setting delivers the same
result as the default: no lost findings, no rework. Cost counts per finished
task, retries included. Otherwise set neither, and the default stays.

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

1. Pick the class. A task that mixes classes, or whose class you hesitate
   over, is `judgement`.
2. Start the brief with the line `task-class: <class>`; the spawn hook logs
   it together with `model`, `effort` and the Agent `description`.
3. Set `model` and `effort` from the row; for `judgement` set neither.

- An agent type whose definition sets its own model (Explore, Plan, the
  cavecrew agents) keeps it; never pass `model` or `effort` for it.
- Never pass `fable` or `opus`: neither is cheaper than the default.
- A Haiku agent that reports the task needs judgement, or returns an
  incomplete result, is not retried on Haiku: the default continues it.
- Never change the default itself (settings, `CLAUDE_CODE_SUBAGENT_MODEL`,
  agent definitions); this skill only chooses per call.

## Feedback

Once you have judged the subagent's result, rate it under the same Agent
`description`:

```bash
${CLAUDE_SKILL_DIR}/scripts/log.py feedback --description "<description>" --completed yes|no --tests pass|fail|none --redo yes|no
```

`--redo yes` when the default had to redo or finish the work. When the
operator later asks a follow-up question about that result or corrects it:

```bash
${CLAUDE_SKILL_DIR}/scripts/log.py followup --description "<description>" --text "<question or correction>"
```

All sessions share `~/.local/state/agents-council/subagent-model.jsonl`.
Inside a sandbox that cannot write it, the script prints the line as
`pending:` and the PostToolUse hook stores it.

## Evaluation

`log.py report` shows per task class, model and effort the runs, the rated
runs and the share with the same result: completed, not redone, no failing
test, no follow-up. A row is added, or a cheaper setting extended to a class,
only when the report shows at least 90 % over at least 20 rated runs, and only
after the operator confirms it (for example through `/autotune`). A row whose
rate falls below 90 % over 20 rated runs goes back to the default. `sonnet`
enters the table only this way, and a trial run on a setting the table does
not hold needs the operator's order.
