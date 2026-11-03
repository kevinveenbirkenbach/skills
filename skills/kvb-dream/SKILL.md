---
name: kvb-dream
description: >
  Process the last 24 hours of every repository and session: memory,
  improvements, kvb-optimize, cleanups. Trigger on a request to learn from
  recent work.
---

Replay what happened, separate what held from what broke, keep only
conclusions that survive an attack, then optimize and clean up.

## Objective

Make the next run measurably less likely to repeat each failure found; what
changes no future behaviour is not recorded. An error class is closed only by
something structural (test, lint rule, CI check, hook, written rule in the
agent instructions, skill), never by "be more careful". Per closed class,
report the confidence the next run can hold, calibrated as the
`kvb-check-confidence` skill requires, and name what is still open.

## Scope

Every repository and session this agent touched in the window: its
transcripts' working directories and worktrees, its `kvb-org-rasci` task
workdirs, the current one. Window: 24 hours, or wider on request (`7d` after
the command). State both in one table first. Recall and score each repository
on its own; a finding goes only into its own project's memory. Run only when
the operator asks; read `hints.md` next to this file when a hint appears or
before changing the reminder.

## Step 1: recall

The actual record per repository, not your recollection:

- **History**: `git log --since` over all branches plus `--reflog` (resets,
  rebases, amends), with `--stat`.
- **Working state**: `git status`, staged and unstaged diff, stashes.
- **CI**: the window's runs, conclusions, and each red run's failing log line,
  not the job title.
- **Reviews**: pull requests and issues touched, with review comments.
- **Register**: `rasci.py tools` ranks the tools the tasks ran (refactoring
  candidates); `get <task>` shows objective, roles, workdir, artifacts.
- **Memory**: each project's memory directory and `MEMORY.md`, to extend
  recorded findings instead of repeating them.
- **Instructions**: `CLAUDE.md`, `AGENTS.md`, the project's skills: which rule
  a mistake violated.
- **Sessions**: readable transcripts, for operator corrections that never
  reached a commit.

## Step 2: score

Every action, with evidence (`sha`, `file:line`, run id):

- **Held**: shipped and still proven: green CI, a passing test covering it, no
  revert, no follow-up fix.
- **Broke**: reverted, amended, hot-fixed later, red CI, or corrected by the
  operator; ending green does not undo the failed first attempt.
- **Unknown**: no verification either way, so no win; a finding of its own,
  never a quiet pass.

## Steps 3 to 6: findings

When the record holds a pattern or an expensive failure, read
`hypotheses.md` next to this file. Offer each improvement, ranked by
evidence, in its own `AskUserQuestion` with `multiSelect: false`: `Apply
now`, `Record as a task`, `Skip`.

## Step 7: optimize

Run the `kvb-optimize` skill with this run's findings as its evidence, so none
of its skills re-collects them; its `kvb-transcend` pass carries every
in-scope session's scripts, tests and skills into their repositories.

## Step 8: clean up

The `kvb-cleanup` skill for the disk, `/tmp`, Docker and agent directories the
window filled, with the finished tasks' artifacts (`rasci.py artifacts
--ended`) as candidates; then the `kvb-git-branch-gc` skill for every
in-scope repository's merged branches and worktrees. Each keeps its own
confirmations; the dream never writes, deletes or commits for them. Close
with `date +%s > ~/.claude/.dream-stamps/"$CLAUDE_CODE_SESSION_ID"`, so the
next hint is twelve hours out.

## Rules

- Read-only until step 6: the dream writes memory; repository code changes
  only on an explicit radio answer.
- An empty window is valid: report "nothing in the last 24 hours" per
  repository and skip it; never invent activity.
- Report the whole ledger: held, broke, unknown, surviving findings, refuted
  hypotheses with why they fell.
