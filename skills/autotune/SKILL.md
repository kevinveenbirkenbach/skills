---
name: autotune
description: >
  Generate new agent skills and optimize existing ones so the agent works more
  efficiently: fewer input and output tokens, fewer errors, more focus, and
  learnings that persist across sessions. Every proposal is confirmed with the
  operator through single-select (radio button) questions. Trigger ONLY on an
  explicit operator request (/autotune, "autotune", "tune the skills"); never
  run it on your own initiative. Portable across projects.
---

Autotune turns observed friction into durable skills. It runs on demand only,
it changes nothing without an explicit answer from the operator, and every
skill it writes or rewrites lands in the operator's skills repository.

## Trigger discipline

- Run **only** when the operator asks: `/autotune`, "autotune", "tune the
  skills", or an equivalent instruction.
- The 60-minute reminder hook is a hint for the operator, not a trigger. When it
  fires, print the hint and continue the operator's actual request.
- Never propose, write, or edit a skill as a side effect of unrelated work.

## Step 1: collect evidence

Before asking anything, gather concrete friction from the current session and,
where readable, from the project's memory and agent instruction files:

- **Token waste**: repeated file re-reads, whole-file reads where a range was
  enough, long tool output pasted back, re-running a command instead of
  grepping a saved log, verbose report prose.
- **Errors**: rejected tool calls, permission prompts, retried commands,
  corrections the operator had to give twice.
- **Focus loss**: work that drifted beyond the request, unrequested tests or
  deploys, questions that stalled an autonomous run.
- **Lost learnings**: facts re-derived this session that a memory file or a
  skill should already have carried.

List each finding as one line: `symptom -> cost -> candidate fix`. Skip
anything that happened once and is not a pattern.

## Step 2: ask, do not decide

Use `AskUserQuestion` with `multiSelect: false` so every question renders as
radio buttons. Never assume an answer, never batch several decisions into one
option, and never write a file before the answers are in.

Ask in this order, at most four questions per call:

1. **Scope** - "What should autotune do this run?" Options: `Create a new
   skill`, `Optimize an existing skill`, `Both`, plus the ranked findings if
   more than one candidate exists.
2. **Target** - which finding becomes a skill, or which existing skill gets
   optimized. One option per candidate, each with its measured cost in the
   description.
3. **Shape** - for a new skill: `Standalone skill`, `Row in the shortcuts
   skill`, `Extend an existing skill`, `Memory entry instead of a skill`.
   For an optimization: `Tighten wording only`, `Change the trigger`, `Add
   rules`, `Split into two skills`, `Merge into another skill`.
4. **Placement** - `Operator skills repository (portable)` or
   `This project's skills directory (project-specific)`.

Present the drafted skill text (name, trigger phrasing, body outline) and ask
for a final `Write it` / `Revise it` / `Discard` confirmation before touching
disk. Rewrites of an existing skill additionally show a before/after diff of
the changed lines in that confirmation.

## Step 3: write

- Portable skills go to `skills/<name>/SKILL.md` in the operator's skills
  repository; project-specific ones to that project's skills directory.
- Frontmatter carries `name` and a `description` that states what the skill
  does **and** when to trigger it - the description is the only part loaded into
  every session, so it decides whether the skill ever fires.
- Body is thin and single-purpose: the smallest instruction that changes
  behaviour. Route to an authoritative doc instead of duplicating it.
- Optimizing an existing skill means the file gets shorter or sharper, not
  longer. Delete rules the agent already follows, merge duplicated ones, and
  cut every sentence that does not change an action.
- Report what changed in at most three lines, then refresh the reminder stamp
  so the next hint is an hour out: `date +%s > ~/.claude/.autotune-stamp`.

## Rules

- One skill per run unless the operator picked `Both`; a broad rewrite of the
  whole collection is not what autotune is for.
- Never write a skill for one-off work, for secrets, or for behaviour an
  existing skill already covers - propose extending that skill instead.
- A skill that saves tokens but loses correctness is a regression; validation,
  error handling, and security steps are never the thing that gets trimmed.
- Efficiency claims stay honest: name the observed friction the skill removes,
  never a guessed percentage.
