---
name: kvb-org-matrix
description: >
  One matrix of everything in flight with the kvb-check-score line per item.
  Trigger on "status", "übersicht", "wo stehen wir".
---

One-shot overview, no side effects: it reads state and reports it, never
edits, stages, commits, deploys or starts work. The operator decides what to
act on.

## Collect the state

In parallel; skip a source the session lacks, and never invent a row for one
you could not read:

1. **Tasks**: the `kvb-org-rasci` register first, then the session's todo
   list, the operator's goals this session, and the requirement or plan
   documents the work follows.
2. **Peers**: `council.py list` (the `kvb-org-organize` skill) and the radio
   store, `radio.py show --all` (the `kvb-org-radio` skill); never message a
   peer for status.
3. **Working tree**: `git status --short` and `git log --oneline -10`:
   uncommitted and untracked files are open work, commits since the branch
   point closed work.
4. **Running**: background jobs, spawned agents not yet reported, scheduled
   `/loop` wake-ups, remote runs (CI, deploys). Poll their live state; a job
   is not "running" because you started it.
5. **Remote**: open PRs and issues for the branch and their check
   conclusions, when a forge CLI is available.

## The matrix

One table, most-blocking first, one row per item:

| Item | State | Score | Evidence / next step |

- **State**: `open`, `running`, `blocked`, `done`. `done` means verified (a
  passing run, a green check, a reproduction that now succeeds); work that
  merely looks finished is `open`.
- **Score**: the `kvb-check-score` line (🎯 fix, 💥 break, 🌱 efficiency,
  ⚡ speed, 🏆 score) per the `kvb-check-confidence` skill, only for rows
  that changed something; `-` for pure observation rows.
- **Evidence / next step**: for `done` the strongest proof line (what ran,
  what it returned), otherwise the single next action.

Then at most three lines:

- **Blocked on**: what needs the operator (a decision, a credential, an
  approval); omit when nothing does.
- **Residuals**: what keeps the lowest confidence below 100.
- **Running**: what reports back on its own, so the operator need not wait
  on it.

## Rules

- Cover everything in scope, including work the operator did not ask about:
  a forgotten background job or an unpushed commit is what the matrix exists
  to surface.
- Report what the poll returned, never a predicted result; a running item
  has no score yet.
- One row per item, no per-item paragraphs; the operator asks when a row
  needs explaining.
