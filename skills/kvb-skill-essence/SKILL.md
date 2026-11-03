---
name: kvb-skill-essence
description: >
  Compact skills and memory after a health pass for dead weight. Trigger when
  skills or MEMORY.md grow too long or duplicate.
---

Shorter, not thinner. Every fact that still earns its place survives; what goes
is repetition, narration, and entries nothing loads any more.

## What costs context

Compact by how often a thing loads, not by its size:

1. **`MEMORY.md`** and every skill's **`description`** load into *every*
   session: a wasted line is paid on every turn. Highest leverage by far.
2. **Skill bodies** load when the skill fires: paid only on use.
3. **Memory files** load on recall.

A 200-line body firing twice a month costs less than four bloated `MEMORY.md`
pointers. Rank the work accordingly and say so in the report.

## Step 1: ask for the scope

Never assume the target. One `AskUserQuestion`, `multiSelect: true`:

- **Skills repository**: the portable `skills/*/SKILL.md` set.
- **This project**: its `.claude/skills` and `.agents/skills`, its memory
  directory and `MEMORY.md`.
- **Home**: `~/.claude` and `~/.agents` (skills, rules, commands, agents).

Take nothing outside what was ticked. Read `memory.md` next to this file when
the scope holds a memory directory or `MEMORY.md`.

## Step 2: doctor

Before compacting, find what is broken or dead, each finding with its path:

- The same rule in two or more skills: one is authoritative, the rest drift.
- A first-party skill shadowing a locked or vendored one.
- Frontmatter missing `name` or `description`, or a `description` saying what
  the skill does but never when it fires: it costs context every session and
  never triggers.

Dead entries are deleted, not compacted. Fix or report the broken ones; never
compact around a stale citation, or the error survives denser.

## Step 3: compact

Cut:

- What the repository already records: code structure, git history,
  `CLAUDE.md`/`AGENTS.md`.
- A rule the agent follows anyway.
- The second and third statement of a rule; keep the authoritative one and
  point at it.
- Narration, hedging, and worked examples beyond the one carrying the point.
- A deterministic step-by-step procedure: hand it to the `kvb-skill-compile`
  skill, which replaces it with a script call.

Keep any fact with no other home (it is not redundancy) and the trigger
wording of a `description`: tighten it, never drop the "when". Dates stay
absolute; never introduce "recently" while shortening.

## Step 4: show the diff, then write

Write in place: an essence beside the original saves nothing, the original
still loads. A git repository needs a clean status for the rewritten paths,
so git alone reverts every edit; not clean: report and stop. `~/.claude` and
`~/.agents` are usually not under git: copy each file to `<file>.pre-essence`
first.

Present per file the diff and the lines and characters saved; ask one
confirmation for the batch; write only after it.

## Step 5: verify

- Re-run the target's own validation if it has one (in a skills repository its
  test suite: frontmatter, lock, shadowing), admitted under the
  `kvb-org-organize` Capacity rules.
- Re-read each rewritten file: every kept fact is still stated, not merely
  implied.
- Report the before and after loaded-context figure for the always-loaded
  surface (`MEMORY.md` plus all descriptions) apart from the rest: that number
  is the point of the run.

## Rules

- Deleting is the goal; rewriting shorter the fallback.
- A skill that never fired is a deletion candidate, not a compaction one: say
  so and let the operator decide.
- `caveman-compress` is no rival: it rewrites one named file's wording; this
  removes what should not be there. Run this first: compressing a dead entry
  is pure waste.
