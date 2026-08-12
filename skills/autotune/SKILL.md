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

Its objective is the `optimize` skill's: every proposal must cut tokens or time
and raise quality — follow that skill's three axes and rules, and drop any
candidate that moves none of them.

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

## Persistence

A skill that exists only under `.claude/skills` is lost on the next install, and
one that exists only in the repository is not live until the next restart — so
every skill is written to **both**, in this order:

1. **Locate the operator's skills repository.** Take the first hit: the
   `SKILLS_REPO` environment variable; the current repository, when it holds
   `skills-lock.json` and a `skills/` directory; `pkgmgr path skills`; a git
   checkout named `skills` under the usual roots
   (`~/Repositories/*/*/skills`, `~/git`, `~/src`, `~/Projects`) carrying
   `skills-lock.json`. If none matches, ask the operator for the path with a
   single-select question — never skip the repository and write only the live
   copies.
2. **Write the source of truth**: `skills/<name>/SKILL.md` in that repository
   (portable skills), or `skills/<name>/SKILL.md` in the current project
   (project-specific ones). This is the copy that gets committed.
3. **Mirror it live**, so it works without a reinstall: copy the skill's whole
   directory to `~/.claude/skills/<name>/` and `~/.agents/skills/<name>/`, and
   for a project-specific skill additionally to that project's
   `.claude/skills/<name>/` and `.agents/skills/<name>/`. Copy the directory,
   not just `SKILL.md`, so hooks and references come along.

Report all written paths. Deleting or renaming a skill follows the same list in
reverse — remove the mirrors too, or the old name keeps firing.

## Step 3: write

- Write the skill to every location the **Persistence** section lists.
- Frontmatter carries `name` and a `description` that states what the skill
  does **and** when to trigger it - the description is the only part loaded into
  every session, so it decides whether the skill ever fires.
- Body is thin and single-purpose: the smallest instruction that changes
  behaviour. Route to an authoritative doc instead of duplicating it.
- Optimizing an existing skill means the file gets shorter or sharper, not
  longer. Delete rules the agent already follows, merge duplicated ones, and
  cut every sentence that does not change an action. Route that compaction
  through the `essence` skill instead of trimming by hand: it runs a health
  pass for dead pointers and rules duplicated across skills before cutting
  anything, ranks by what loads in every session, and shows the diff before it
  writes. It asks for its own scope — answer with the skill being optimized.
- Report what changed in at most three lines, then refresh the reminder stamp
  so the next hint is an hour out: `date +%s > ~/.claude/.autotune-stamp`.

## Rules

- One skill per run unless the operator picked `Both`; a broad rewrite of the
  whole collection is not what autotune is for.
- Never write a skill for one-off work, for secrets, or for behaviour an
  existing skill already covers - propose extending that skill instead.
- The `optimize` skill's rules decide what counts as an improvement: at least
  one axis better, none damaged, and the claim named as observed friction rather
  than a guessed percentage.
