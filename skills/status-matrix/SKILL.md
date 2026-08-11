---
name: status-matrix
description: >
  Print one matrix of everything currently in flight: open and closed tasks,
  running workflows and background jobs, plus confidence and break risk per
  item. Trigger on /status-matrix, "status", "übersicht", "wo stehen wir", or
  whenever the operator asks what is done, what is left, or what is still
  running. Portable across projects.
---

One-shot overview, no side effects: this skill reads state and reports it. It
never edits files, stages, commits, deploys, or starts work — the operator
decides what to act on after reading the matrix.

## Collect the state

Gather in parallel, skip any source the session does not have, and never invent
a row for a source you could not read:

1. **Tasks** — the session's todo list, the operator's stated goals this
   session, and any requirement or plan documents the work follows.
2. **Working tree** — `git status --short` and `git log --oneline -10`:
   uncommitted files are open work, commits since the branch point are closed
   work. Untracked files count as open.
3. **Running** — background bash jobs, spawned agents not yet reported,
   scheduled `/loop` wake-ups, and remote runs (CI, deploys). Poll their live
   state; a job you started is not "running" because you started it.
4. **Remote** — open PRs and issues for the branch, and their check
   conclusions, when a forge CLI is available.

## The matrix

One table, most-blocking first, one row per item:

| Item | State | Conf. | Break risk | Evidence / next step |

- **State**: `open`, `running`, `blocked`, `done`. `done` means verified —
  a passing run, a green check, a reproduction that now succeeds. Work that
  merely looks finished is `open`.
- **Conf.** and **Break risk**: two separate percentages per the `confidence`
  skill — probability the item does what it claims, and probability it breaks
  something else. Only for rows that changed something; `—` for pure
  observation rows.
- **Evidence / next step**: for `done`, the strongest proof line (what ran,
  what it returned). For everything else, the single next action.

Then at most three lines below the table:

- **Blocked on**: what needs the operator (a decision, a credential, an
  approval) — omit when nothing does.
- **Residuals**: what keeps the lowest confidence number below 100.
- **Running**: what will report back on its own, so the operator does not wait
  on it manually.

## Rules

- Cover everything in scope, including work the operator did not ask about —
  a forgotten background job or an unpushed commit is exactly what the matrix
  exists to surface.
- Report what the poll returned, never a predicted result for work still in
  flight; a running item has no confidence number yet.
- Compress: one row per item, no per-item paragraphs. If a row needs
  explaining, the operator will ask.
