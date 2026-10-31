---
name: kvb-code-test
description: >
  Discover the Makefile's test targets, let the operator pick, run and report;
  fix mode loops until green. Trigger on /kvb-code-test, /kvb-code-test --fix, or when the
  operator asks to run the tests, make them pass, or get the suite green.
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

Do not fix what failed unless the operator asks - report first. A request to
make the tests pass, fix them, or get the suite green (`/kvb-code-test --fix`) switches
to fix mode.

## Fix mode

The contract is narrow: the code becomes correct, the tests stay honest.

One iteration is: run -> read the failure -> one root cause -> one fix ->
re-run. Never batch several speculative fixes into one iteration; a green run
after three simultaneous changes proves nothing about which one mattered.

- **Run** the failing target alone, the fastest command that reproduces the
  failure. Widen back to the full selection only when that target is green.
- **Diagnose** from the actual error output before touching a file. Apply the
  `kvb-ci-triage` skill to reach a verified root cause; for a cause still unclear
  after one look, apply `kvb-think-dialectic` rather than guessing twice. Say in one line
  which side is wrong:
  - **Code**: the test states the intended behaviour. Fix the code.
  - **Test**: it encodes an outdated or incorrect expectation. Fix it only with
    a stated reason why the old expectation was wrong, never because the code
    disagrees with it.
  - **Environment**: missing dependency, stale container, absent env var,
    unbuilt artefact. Fix the environment or report it; do not patch code
    around it.
- **Fix** with the smallest change that addresses the root cause, in the
  project's idioms and under the `kvb-code-no-defaults` and `kvb-code-no-comments` rules.
  Forbidden without explicit operator approval: deleting, skipping, `xfail`-ing
  or commenting out a failing test; loosening an assertion to what the code
  produces; swallowing the exception the test surfaces; retries, sleeps or
  reruns over a flaky failure; disabling a linter rule, a type check or a
  target. Any of these is a report item, not a fix: a suite that is green
  because the failing test no longer runs is a regression disguised as success.
- **Re-run** the same target, then every target that was already green; only
  a full green selection ends the loop.

Stop and report, without asking for permission to stop:

- **Green**: the full selection passes.
- **No progress**: the same failure survives 3 iterations, or the failure count
  stops falling across 3 iterations. Report the root cause reached, what was
  tried, and why each attempt failed.
- **Beyond the mandate**: the real fix is an API change, a dependency bump, a
  schema migration, or a redesign. Name it with its minimal diff and let the
  operator decide.
- **Oscillation**: fixing A re-breaks B and vice versa. Report both; that is a
  design problem, not a test problem.
- **Flaky**: a target passes and fails without any change. Report both
  outputs; never rerun until green.

Emit one line per iteration: target, failure, hypothesis, change. The final
report gives per iteration what failed, the root cause, the fix and the
result; the final state of every selected target with the verbatim output of
anything still failing; everything deliberately not done; and the command
reproducing the final state. State confidence per the `kvb-check-confidence` skill. Do
not commit unless the operator asked for a commit.
