---
name: kvb-skill-tune
description: >
  Generate or sharpen skills from observed friction, each proposal confirmed.
  Trigger only on "autotune", "tune the skills" or through kvb-optimize.
---

## Objective

Shared by kvb-skill-tune, kvb-skill-auto and kvb-check-confidence: every skill,
rule or report about the agent's own working is judged on three axes; a
proposal naming none is a preference.

- **Tokens**: fewer tokens for the same result (read the range, grep the saved
  log, route to the authoritative doc, report in lines).
- **Time**: fewer round trips and less waiting (independent calls in parallel,
  one command that answers, no polling for what the harness reports).
- **Quality**: fewer errors and less rework (verify instead of assuming,
  persist learnings so a mistake is paid once).

A change improves at least one axis and damages none; cheaper but less correct
is a regression. Quality is never the currency: validation, error handling,
tests and security steps are not cut. Name the observed friction (the re-read,
the retry, the correction given twice) and its cost, never a guessed
percentage. Drop work before optimizing it. Persist it in a skill or memory
entry, or pay again.

## Trigger discipline

Run only on the operator's request (its command, "autotune", "tune the skills"
or an equivalent) or inside a `kvb-optimize` run the operator started,
directly or through `kvb-dream`, whose hint is its only reminder. Never write
or edit a skill as a side effect of other work.

## Step 1: collect evidence

Before asking, gather friction from the session and, where readable, the
project's memory and agent instruction files: token waste (re-reads, whole-file
reads, pasted tool output, re-runs instead of a grepped log, verbose prose),
errors (rejected calls, permission prompts, retries, corrections given twice),
focus loss (drift beyond the request, unrequested tests or deploys, questions
that stalled an autonomous run), lost learnings (facts memory or a skill should
have carried). Own scripts outside any repository go to the
`kvb-skill-transcend` skill (this one takes the frictions they reveal); a step
worked by hand although its result follows from its inputs goes to the
`kvb-skill-compile` skill. One line per finding: `symptom -> cost -> candidate
fix`; skip one-offs that form no pattern.

## Step 2: ask, do not decide

`AskUserQuestion` with `multiSelect: false`, at most four questions per call,
in this order; never assume an answer, never batch decisions into one option:

1. **Scope**: "What should kvb-skill-tune do this run?" `Create a new skill`,
   `Optimize an existing skill`, `Both`, plus the ranked findings when there
   are several candidates.
2. **Target**: one option per candidate, its measured cost in the description.
3. **Shape**: new: `Standalone skill`, `Extend an existing skill`, `Memory
   entry instead of a skill`. Optimization: `Tighten wording only`, `Change
   the trigger`, `Add rules`, `Split into two skills`, `Merge into another
   skill`, `Compile deterministic steps into a script` (`kvb-skill-compile`).
4. **Placement**: `Operator skills repository (portable)` or `This project's
   skills directory (project-specific)`.

Then show the draft (name, trigger phrasing, body outline; a rewrite adds a
before/after diff of the changed lines) and ask `Write it` / `Revise it` /
`Discard`. Nothing touches disk before `Write it`.

## Persistence

Every skill goes to its source of truth `skills/<name>/SKILL.md` in the skills
repository (`SKILLS_REPO` first) or the project, and live to
`~/.claude/skills/` and `~/.agents/skills/`. Read `write.md` next to this file
before writing, renaming or deleting a skill.

## Rules

- One skill per run unless the operator picked `Both`; no broad rewrite of the
  whole collection.
- No skill for one-off work, for secrets, or for behaviour an existing skill
  covers: propose extending that skill.
- The **Objective** decides what counts as an improvement.
