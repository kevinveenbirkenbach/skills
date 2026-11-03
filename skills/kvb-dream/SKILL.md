---
name: kvb-dream
description: >
  Process the last 24 hours of every repository and session: memory,
  improvements, kvb-optimize, cleanups. Trigger on /kvb-dream or a request
  to learn from recent work.
---

Sleep on the work: replay what happened, separate what held from what broke,
keep only the conclusions that survive an attack, then optimize and clean up.
Dreaming processes everything. A dream that flatters the dreamer is worthless —
an unverified success counts as unknown, not as a win.

## Objective

The dream exists to raise the confidence of every future run until the
mistakes it found cannot happen again. Judge every finding, memory
entry, and proposal by one question: does it make the next run measurably less
likely to repeat this failure? What changes nothing about future behaviour is
not worth recording.

A class of error counts as closed only when something structural prevents it —
a test, a lint rule, a CI check, a hook, a written rule in the agent
instructions, or a skill. "Be more careful next time" closes nothing. Report the
confidence the next run can now hold on each closed class, calibrated as the
`kvb-check-confidence` skill requires, and name what is still open.

## Scope

Every repository and session this agent touched in the window: the
repositories named by its session transcripts (working directories and
worktrees), by the workdirs of its `kvb-org-rasci` register tasks, and the
current one. The default window is the last 24 hours — the operator may widen
it (`/kvb-dream 7d`). State the repositories and the window in one table before
you start. Each repository is recalled and scored on its own; a finding goes
into the memory of the project it concerns, never mixed with another's.

Run only when the operator asks. Two hints point at it, neither is a trigger:
`hooks/reminder.sh` tells each agent at most once every twelve hours (stamped
per session in `~/.claude/.dream-stamps/`), and the `kvb-dream-notify.timer`
user timer shows a GNOME notification daily at 17:00 local time, catching up
once after a missed run. Print the hint and continue with the actual request.

## Step 1: recall

Gather the window's actual record per repository, not your recollection of it:

- **History**: `git log --since` across all branches plus `--reflog`, with
  `--stat`; the reflog carries the resets, rebases, and amends the log hides.
- **Working state**: `git status`, the staged and unstaged diff, stashes.
- **CI**: the runs created in the window, their conclusions, and the failing
  logs of the red ones — the failing log line, not the job title.
- **Reviews**: pull requests and issues touched in the window, and the review
  comments on them.
- **Register**: the `kvb-org-rasci` register: `rasci.py tools` ranks the
  scripts and tools the window's tasks ran, the refactoring candidates;
  `get <task>` shows a task's objective, roles, workdir and artifacts.
- **Memory**: each project's memory directory and its `MEMORY.md` index — the
  findings already recorded, so the dream extends them instead of repeating them.
- **Instructions**: `CLAUDE.md`, `AGENTS.md`, and the project's own skills, to
  see which rule a mistake actually violated.
- **Sessions**: the readable session transcripts touched in the window, for the
  operator corrections that never reached a commit.

## Step 2: score

Classify every action in the window, each with its evidence (`sha`, `file:line`,
run id):

- **Held** — shipped and still proven: green CI, a passing test that covers it,
  no revert, no follow-up fix.
- **Broke** — reverted, amended, hot-fixed by a later commit, red CI, or
  corrected by the operator. A failure that ended green is still a failure; count
  the detour, not only the destination.
- **Unknown** — no verification exists either way. Unknown is a finding in its
  own right, never a quiet pass.

## Step 3: hypothesize

Turn the scored record into falsifiable hypotheses, each written as *cause →
predicted consequence → what would disprove it*. Take a pattern (two or more
occurrences) or a single expensive failure; drop the one-off noise. A hypothesis
that nothing could disprove is not a hypothesis — cut it.

## Step 4: dialectic

Put every surviving hypothesis through the `kvb-think-dialectic` skill: thesis,
independent skeptics, synthesis, iterated to ~99%. What survives becomes a
finding. What gets refuted is recorded as discarded **with the refutation**, so
the next dream does not re-derive it.

## Step 5: write memory

Persist the findings in the memory directory of the project they concern: one file per fact, one
pointer line in `MEMORY.md`. Update the file that already covers a fact instead
of adding a duplicate, and delete the memories this run disproved. Absolute
dates, never "yesterday". Nothing that the repository already records — code
structure, git history, `CLAUDE.md` — belongs in memory.

## Step 6: offer the improvements

Two kinds come out of the findings:

- **Code** — the change to the affected repository's source, tests, config, or CI that
  the finding calls for.
- **Agent instructions** — the missing or wrong rule in `CLAUDE.md`,
  `AGENTS.md`, the project's own skills, or the contributor docs. Every mistake
  the agent repeated in the window is a candidate: quote the line that failed to
  prevent it, or name the rule that is absent, and propose the exact wording.

Ask for each one with `AskUserQuestion` and `multiSelect: false` so it renders
as radio buttons: the improvement, the evidence behind it, and the options
`Apply now`, `Record as a task`, `Skip`. Ranked by evidence, one question per
improvement. No repository file changes before an answer comes back.

## Step 7: optimize

With the dialectic done and memory written, run the `kvb-optimize` skill and
hand it this run's findings as its evidence, so none of its skills
re-collects them. Its pass includes the `kvb-transcend` skill, which carries
the scripts, tests and skills of every session in scope into their
repositories.

## Step 8: clean up

Run the `kvb-cleanup` skill for the disk, `/tmp`, Docker and agent
directories the window filled, with the artifacts of the window's finished
register tasks (`rasci.py artifacts --ended`) as its candidates, then the
`kvb-git-branch-gc` skill for the merged branches and worktrees of every
repository in scope.

Every skill in steps 7 and 8 keeps its own confirmation steps; the dream never
writes, deletes or commits on their behalf. Close the run by refreshing this
agent's reminder stamp, so its next hint is twelve hours out:
`date +%s > ~/.claude/.dream-stamps/"$CLAUDE_CODE_SESSION_ID"`.

## Rules

- Evidence or unknown: a claim about what held needs a green signal, and its
  absence is reported as unknown rather than assumed.
- Honest scoring: reverts, amends, and follow-up fixes are failures of the first
  attempt even when the final state is green.
- Read-only until step 6: the dream inspects, and writes memory; repository code
  changes only on an explicit radio answer.
- An empty window is a valid result — report "nothing in the last 24 hours" per
  repository and skip it. Never invent activity to have something to dream
  about.
- Prefer the structural fix over the remembered one: a test, check, hook, or
  written rule that makes the error impossible beats a memory entry that only
  reminds you of it.
- Report the whole ledger: held, broke, unknown, the surviving findings, the
  refuted hypotheses with why they fell, and the confidence each closed error
  class now carries into the next run.
