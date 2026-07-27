---
name: test
description: >
  Discover the test targets of the project's Makefile, let the operator pick
  which ones to run, then run them and report. Trigger on /test or when the
  operator asks to run the tests, the test suite, or a specific test target
  without naming the exact command. Portable across projects.
---

The Makefile is the source of truth for how this project runs tests. Never
invent a command (`pytest`, `npm test`, `go test`) while a Makefile target
exists - the target carries the project's env vars, build dependencies and
container setup.

## Step 1: find the targets

From the repository root:

```bash
grep -nE '^test[A-Za-z0-9_.-]*:' Makefile
```

Read the matched rules plus their prerequisites, so the selection list can say
what each one actually does (delegated script, container build, sub-targets).

Edge cases, handled explicitly rather than guessed around:

- **No Makefile**: say so in one line, name the test runner the project does
  use (from `pyproject.toml`, `package.json`, `tox.ini`, CI workflow), and ask
  before running anything.
- **No `test*` target**: report the targets that do exist and stop.
- **Included makefiles** (`include foo.mk`): grep those too.
- **Aggregate targets**: a target whose recipe is only other test targets (e.g.
  `test: test-unit test-integration`) is the "run everything" entry - mark it as
  such in the list, do not expand it into its parts silently.

## Step 2: offer the selection

Ask with `AskUserQuestion`, `multiSelect: true`, one question. Options are the
discovered targets, each with a one-line description of what it runs. Order the
aggregate/full target first and label it as the complete suite.

The tool takes at most 4 options. With more targets than that:

- print the **complete** discovered list as text first, one line per target, so
  nothing is hidden, then
- offer the 4 most useful entries (aggregate first, then the ones matching the
  operator's stated intent or the files currently uncommitted), and note that
  "Other" accepts any target name from the printed list.

Never silently truncate. If the operator already named a target in their
request, skip the question and run it.

## Step 3: run

Run the selected targets in the order the operator listed them, one `make`
invocation per target, each as its own command so a failure is attributable:

```bash
make <target>
```

Do not add `-k`, do not reorder, do not substitute a faster equivalent. If a
target needs a long timeout (container builds, e2e), set it on the Bash call
rather than backgrounding blindly.

Stop after the first failing target unless the operator asked for all of them -
a later suite running against a broken build produces noise, not information.

## Step 4: report

Per target: pass/fail plus the failing test names and the exact error output,
quoted verbatim. Never paraphrase a failure. Then one line with the exact
command to reproduce the failure alone.

Do not fix what failed unless the operator asks - report first. If the operator
does ask for a fix, apply the `triage` skill to it.
