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

## Step 2: refactor each file

Read the whole file first, then apply the standards that the surrounding code
and the project's own config already establish (formatter config, linter rules,
existing idioms) over any generic preference of your own:

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

## Step 3: keep behaviour provable

- Never fold a bug fix, a feature, or a dependency change into a refactor.
  Found a real bug? Name it in the report and leave it for a separate change.
- Run the cheap checks the project already has for the touched files (formatter,
  linter, the module's own unit tests). Do not start a full suite, a build, or a
  deploy on your own initiative - propose it and let the operator trigger it.
- State plainly what was verified and what was not. An unverified refactor is
  reported as unverified.

## Step 4: report

One line per file: what changed and why it is safe. Then one line naming what
was deliberately left alone (architectural findings, bugs, files skipped) and
the exact command the operator can run to validate. Do not commit unless the
operator asked for a commit.
