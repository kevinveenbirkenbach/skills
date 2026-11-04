---
name: kvb-code-refactor
description: >
  Refactor every uncommitted file to the project's standards without
  changing behaviour. Trigger when asked to clean up, tidy or polish the
  current changes.
---

The unit of work is the uncommitted change set, not the repository. Behaviour
stays identical: a refactor that changes what the code does is a bug.

## Step 1: fix the file set

Read it from `git status --porcelain`, never from memory: modified, added,
renamed and untracked files, without deleted files, binaries, lockfiles,
vendored trees and generated output. Restate the list in one line before
touching anything; if it is empty, say so and stop.

Never `git stash` or revert a working-tree file to compare: others share this
tree. Read the committed version with `git show HEAD:<path>` into a temporary
file.

## Step 2: get a safety net first

Behaviour stays provable only through a check before and after: tests that
cover the change set run now and give the green baseline; a suite already red
is reported, not refactored around. No coverage: read `net.md` next to this
file before editing.

Light runs (targeted tests, ruff, single lint files) start once `watch.py
admit --kind test-nostack` of the `kvb-org-organize` skill prints `grant`; no
chair request.

## Step 3: refactor each file

Read the whole file first; the project's own standards (formatter config,
linter rules, existing idioms) outrank generic preference. Find callers,
duplicates and existing helpers through the codebase-memory-mcp graph first
(`search_graph`, `trace_path`, `get_architecture`; the `kvb-agent-optimize`
skill sets it up), grep and read after.

- **SRP**: one file, one responsibility; one function, one reason to change.
  A unit that needs an "and" to describe it is two.
- **SPOT**: every fact (constant, path, schema, rule) lives in one place;
  everything else references it.
- **KISS**: the simplest construct that works; no abstraction without a
  second caller today, no configuration for a value that never varies.
- **DRY**: logic is written once; a literal repeated three times is a missing
  constant.
- **File size**: read `size.md` next to this file for a file over 250 lines.
- **Duplication**: fold repeated logic into the existing helper; a new one
  only when two or more call sites need it now.
- **Dead weight**: unused imports, variables and parameters, unreachable
  branches, single-value flags, one-implementation abstractions.
- **Naming**: names state what a thing is, in the file's convention.
- **Shape**: split a function that needs a scroll; return early instead of
  nesting; magic values become a named constant at the use site.
- **Errors**: never widen or swallow a caught exception, never remove a
  validation or security check to shorten code.
- **Comments, defaults**: the `kvb-code-clean` skill.

Never reformat a region without a substantive fix: cosmetic churn buries the
real change. An architectural problem the change set cannot fix is reported,
not half-done.

## Step 4: keep behaviour provable

- Re-run the step 2 net; require the baseline's green result.
- Never fold a bug fix, feature or dependency change into a refactor; name a
  found bug in the report for a separate change.
- Run the project's cheap checks for the touched files (formatter, linter,
  the module's unit tests). Never start a full suite, build or deploy on your
  own: propose it for the operator to trigger.
- Report what was verified and what was not, an unverified refactor as
  unverified.

## Step 5: report

One line per file: what changed and why it is safe. Then one line on what was
deliberately left alone (architectural findings, bugs, skipped files) and the
exact command the operator can run to validate. Commit only when the operator
asked.
