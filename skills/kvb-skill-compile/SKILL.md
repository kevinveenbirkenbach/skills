---
name: kvb-skill-compile
description: >
  Turn deterministic skill steps into tested scripts in the skill's own repo.
  Trigger on a skill step that is a fixed command sequence.
---

A deterministic step's result follows from its inputs alone: fixed command
sequences, output parsing and filtering, counting, thresholds and arithmetic,
format checks, sorting and lookups, state bookkeeping. Such steps become
scripts and their prose shrinks to the call; choosing, explaining and asking
stay prose. Nothing changes before the operator confirms.

## Step 1: scope and owner

The skills named after the command, else every skill of the current
repository. Per skill, its owning repository:

- **Skills repository**: a first-party skill under its `skills/`, and every
  installed copy of one (`~/.claude/skills`, `~/.agents/skills`, a project's
  rendered `.claude/skills`); edit the source, never the copy, by the
  `kvb-skill-tune` skill's **Persistence** section.
- **Another repository**: a skill tracked in that repository's own tree
  (`git ls-files` lists it there), such as a project's `.claude/skills`.
- **Third party**: a `skills-lock.json` entry from a foreign source is not
  compiled; propose the change upstream.

## Step 2: inventory

Read-only. Per skill, every deterministic step with its evidence: how often
sessions ran it (transcripts, `rasci.py tools` of the `kvb-org-rasci`
register) and where an agent got it wrong. One line each:
`skill:step -> deterministic part -> inputs -> output -> runs per use`.

## Step 3: classify

Compile what runs often or went wrong; a one-off stays prose. Per candidate:

- **Language and form**: the owning repository's own (Python standard
  library in the skills repository); no new language, framework or dependency
  without the operator.
- **Interface**: every host path, name and value an explicit parameter (the
  `kvb-code-no-defaults` skill), documented exit codes, `--json` when another
  script or skill consumes the output.
- **Location**: `skills/<skill>/scripts/<verb>.py` with a test under `tests/`
  in the skills repository; elsewhere the owning repository's convention,
  read from its `AGENTS.md`, `CONTRIBUTING` and `Makefile` first.

## Step 4: listen and confirm

Run the `kvb-think-listen` skill on the open points. Then `AskUserQuestion`:
one `multiSelect` with the candidates, nothing preselected, and per pick a
single-select `Write it` / `Revise it` / `Discard` showing the drafted script
and the prose diff.

## Step 5: write

- Write the script, then replace the compiled prose with its call
  (`${CLAUDE_SKILL_DIR}/scripts/<verb>.py ...`) and one line on reading its
  output.
- Every script gets a unit test with a negative control shown once, run once
  `watch.py admit --kind test-nostack` (the `kvb-org-organize` skill) prints
  `grant`; `make test` runs through `queue.py hold` (`kvb-org-queue`).
- In another repository follow its agent rules (claims, worktree, branch); a
  file another line owns goes to that line through the `kvb-org-coordinate`
  skill.
- Leave the result uncommitted for the `kvb-git-commit-next` skill.

## Output

| Skill | Step | Script | Repository | Prose lines cut | Verdict |

Steps left as prose stay with their reason.
