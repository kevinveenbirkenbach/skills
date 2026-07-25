---
name: refactor
description: >
  Refactor every file that is currently uncommitted in the git working tree -
  staged, unstaged and untracked - up to the project's coding standards,
  without changing behaviour. Trigger on /refactor or when the operator asks to
  clean up, tidy, or polish the current changes before committing. Portable
  across projects.
---

The unit of work is the uncommitted change set, not the repository. Behaviour
stays identical: a refactor that changes what the code does is a bug, not a
cleanup.

## Step 1: fix the file set

Read the set from git, never from memory of what was edited:

```bash
git status --porcelain
```

Take modified, added, renamed and untracked files. Drop deleted files, binaries,
lockfiles, vendored trees and generated output. Restate the resulting list in
one line before touching anything; if it is empty, say so and stop.

Never `git stash` and never revert a working-tree file to compare - other agents
and the operator share this tree. Read the committed version with
`git show HEAD:<path>` into a temporary file instead.

## Step 2: get a safety net first

A refactor is only provably behaviour-preserving if something failed before it
and passes after it. Before editing, check what covers the change set:

- **Coverage exists**: run it now and record the green baseline. A suite that
  was already red gets reported, not refactored around.
- **No coverage and the code is testable logic**: write the characterization
  tests first, against the current behaviour - including the behaviour you
  consider wrong, so the refactor cannot silently change it. Keep them small
  and framework-free unless the project already has a framework. Fix the
  captured wrongness in a separate change, never in this one.
- **Not sensibly testable**: pure glue, declarative config, a thin wrapper over
  a service the test would have to mock into meaninglessness, or a project with
  no test setup at all. Say so in one line and refactor without a net; do not
  invent a test harness the project never asked for.

The new tests are part of the deliverable and must still pass unchanged after
the refactor. A test that had to be edited to stay green means the behaviour
moved: revert the refactor, not the test.

## Step 3: refactor each file

Read the whole file first, then apply the standards that the surrounding code
and the project's own config already establish (formatter config, linter rules,
existing idioms) over any generic preference of your own.

Four principles govern the result:

- **SRP**: one file, one responsibility; one function, one reason to change. A
  unit that needs an "and" to describe it is two units.
- **SPOT**: every fact - a constant, a path, a schema, a rule - lives in exactly
  one place and everything else references it.
- **KISS**: the simplest construct that works. No abstraction without a second
  caller today, no configuration for a value that never varies.
- **DRY**: the same logic is written once. A literal repeated three times is a
  missing constant.

Concretely:

- **File size**: no file containing program code exceeds 250 lines. Split the
  overflow along the SRP seam - it is the symptom, not the cause. Description
  and markup languages are exempt (Markdown, YAML, JSON, HTML, translation and
  data files), as is the rare file the language or framework genuinely forbids
  splitting: name that reason in the report, "it was easier" does not qualify.
- **Duplication**: fold repeated logic into the helper that already exists;
  create a new one only when two or more call sites need it now.
- **Dead weight**: unused imports, variables, parameters, branches that cannot
  be reached, flags with a single value, abstractions with one implementation.
- **Naming**: names that state what a thing is, matching the file's convention.
- **Shape**: split a function that needs a scroll to read; collapse nesting by
  returning early; replace magic values with a named constant at its use site.
- **Errors**: never widen a caught exception, never swallow one, never remove a
  validation or a security check to make the code shorter.
- **Comments**: invoke the `comments-clean` skill rather than reimplementing its
  rules here.

Do not reformat regions you have no substantive fix for - cosmetic churn buries
the real change in the diff. If a file's problem is architectural and cannot be
fixed inside the change set, report it instead of half-doing it.

## Step 4: keep behaviour provable

- Re-run the step 2 net and require the same green result as the baseline.
- Never fold a bug fix, a feature, or a dependency change into a refactor.
  Found a real bug? Name it in the report and leave it for a separate change.
- Run the cheap checks the project already has for the touched files (formatter,
  linter, the module's own unit tests). Do not start a full suite, a build, or a
  deploy on your own initiative - propose it and let the operator trigger it.
- State plainly what was verified and what was not. An unverified refactor is
  reported as unverified.

## Step 5: report

One line per file: what changed and why it is safe. Then one line naming what
was deliberately left alone (architectural findings, bugs, files skipped) and
the exact command the operator can run to validate. Do not commit unless the
operator asked for a commit.
