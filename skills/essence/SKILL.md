---
name: essence
description: >
  Compact skills and memory down to their essence so every session loads less
  context, after a health pass that finds the dead weight first. Trigger on
  /essence, or when the operator says the skills or MEMORY.md have grown too
  long, carry duplicates, or eat too much context. Portable across projects.
---

Shorter, not thinner. Every fact that still earns its place survives; what goes
is repetition, narration, and entries nothing loads any more.

## What actually costs context

Compact by how often a thing is loaded, not by how large it is:

1. **`MEMORY.md`** and every skill's **`description`** frontmatter load into
   *every* session. A wasted line here is paid on every single turn. Highest
   leverage by a wide margin.
2. **Skill bodies** load when the skill fires. Worth tightening, paid only on use.
3. **Memory files** load on recall. Lowest leverage — and the place where
   cutting evidence does the most damage.

A 200-line skill body that fires twice a month costs less than four bloated
`MEMORY.md` pointers. Rank the work accordingly and say so in the report.

## Step 1: ask for the scope

Never assume the target. Ask once with `AskUserQuestion` and
`multiSelect: true`, so the operator can tick several:

- **Skills repository** — the portable `skills/*/SKILL.md` set.
- **This project** — its `.claude/skills` and `.agents/skills`, plus the
  project's memory directory and `MEMORY.md`.
- **Home** — `~/.claude` and `~/.agents` (skills, rules, commands, agents).

Take nothing outside what was ticked.

## Step 2: doctor

Before compacting anything, find what is already broken or dead. Report each
finding with its path:

- A `MEMORY.md` pointer whose file is gone, and a memory file no pointer names.
- A dead `[[wikilink]]` — no memory of that name exists.
- A memory asserting a `file:line`, function, or flag that no longer exists.
  Verify against the current tree; a stale citation is worse than no memory,
  because it reads as checked.
- The same rule stated in two or more skills. One is authoritative, the rest
  are drift.
- A first-party skill shadowing a locked/vendored one.
- Frontmatter missing `name` or `description`, or a `description` that says
  what the skill does but never when it fires — such a skill costs context in
  every session and never triggers.

Dead entries are deleted, not compacted. Fix the broken ones or report them;
never compact around a stale citation, or the error survives in denser form.

## Step 3: compact

Cut:

- Anything the repository already records — code structure, git history, what
  `CLAUDE.md`/`AGENTS.md` already say.
- A rule the agent follows anyway without being told.
- The second and third statement of one rule; keep the authoritative one and
  point at it.
- Narration, hedging, and worked examples beyond the one that carries the point.

Keep, always:

- The **why** and the evidence behind a memory — the date, the incident, the
  quoted correction. A rule stripped of its evidence degrades into an
  exhortation and stops changing behaviour.
- Any fact with no other home. If it exists nowhere else, it is not redundancy.
- Trigger wording in a `description`. Tighten it, never drop the "when".

Dates stay absolute. Never introduce "recently" while shortening.

## Step 4: show the diff, then write

Writing happens in place — an essence that lives beside the original saves
nothing, because the original is still what loads.

Preconditions, per target:

- A git repository must have a clean status for the paths being rewritten, so
  every edit is revertable with git alone. Not clean: report and stop.
- `~/.claude` and `~/.agents` are usually not under git. Copy each file to
  `<file>.pre-essence` first.

Then present, per file: the diff, and the lines and characters saved. Ask for
one confirmation covering the batch. Write only after it.

## Step 5: verify

- Re-run the target's own validation if it has one (in a skills repository,
  its test suite: frontmatter, lock, shadowing).
- Re-read each rewritten file and confirm every kept fact is still stated, not
  merely implied by something shorter.
- Report the before/after loaded-context figure for the always-loaded surface
  (`MEMORY.md` plus all descriptions) separately from the rest. That number is
  the point of the run.

## Rules

- Deleting is the goal; rewriting shorter is the fallback. Prefer removing an
  entry over polishing it.
- Never merge two memories whose evidence differs. Two incidents supporting one
  rule are stronger than one; two rules sharing one incident is a fabrication.
- A skill that has never fired is a candidate for deletion, not compaction —
  say so and let the operator decide.
- Nothing is written without the Step 4 confirmation, and nothing outside the
  scope ticked in Step 1.
- `caveman-compress` is not a rival: it rewrites the wording of one named file,
  this removes what should not be there at all. Run this one first — compressing
  a dead entry is pure waste.
