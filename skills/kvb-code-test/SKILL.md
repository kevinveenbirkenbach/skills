---
name: kvb-code-test
description: >
  Run the Makefile test targets the operator picks and report; fix mode loops
  until green. Trigger when asked to run or fix the tests.
---

The Makefile is the source of truth for how this project runs tests. Never
invent a command (`pytest`, `npm test`, `go test`) while a Makefile target
exists: the target carries the project's env vars, build dependencies and
container setup.

## Step 1: find the targets

From the repository root, `grep -nE '^test[A-Za-z0-9_.-]*:' Makefile`, plus
every included makefile (`include foo.mk`). Read the matched rules and their
prerequisites, so the list can say what each one does (delegated script,
container build, sub-targets).

- **No Makefile**: say so in one line, name the runner the project does use
  (`pyproject.toml`, `package.json`, `tox.ini`, CI workflow), and ask before
  running anything.
- **No `test*` target**: report the targets that exist and stop.
- **Aggregate target** (recipe only other test targets, e.g.
  `test: test-unit test-integration`): the "run everything" entry; mark it so,
  never expand it silently.

## Step 2: offer the selection

If the operator already named a target, skip this and run it. Otherwise one
`AskUserQuestion`, `multiSelect: true`: the targets, each with a one-line
description, the aggregate first, labelled as the complete suite. With more
than 4 targets, first print the **complete** list as text, one line per
target, then offer the 4 most useful (aggregate first, then those matching
the operator's intent or the uncommitted files) and note that "Other" accepts
any listed name. Never silently truncate.

## Step 3: run

Before each run, admit it under the `kvb-org-organize` Capacity rules: a
light run (no Docker, about a minute: one test file or module, ruff)
self-admits with
`${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/watch.py admit --kind
test-nostack`; `make test`, quality gates and anything with Docker run in the
background through
`${CLAUDE_SKILL_DIR}/../kvb-org-queue/scripts/queue.py hold --kind <kind>
--task <register task> -- make <target>`, which waits for the rule-based
grant and releases on exit.

Run the selected targets in the operator's order, one `make <target>` per
command so a failure is attributable. No `-k`, no reordering, no faster
substitute. A light target needing a long timeout gets it on the Bash call
instead of blind backgrounding. Stop after the first failing
target unless the operator asked for all: a later suite against a broken build
produces noise, not information.

## Step 4: report

Per target: pass or fail, the failing test names and the exact error output,
quoted verbatim, never paraphrased. Then one line with the exact command
reproducing the failure alone.

Fix nothing unless asked; report first. A request to make the tests pass, fix
them or get the suite green (`--fix`) switches to fix mode: read `fix.md`
next to this file before its first iteration.
