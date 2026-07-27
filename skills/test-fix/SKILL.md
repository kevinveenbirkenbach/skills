---
name: test-fix
description: >
  Run the project's Makefile test targets in a loop - run, diagnose, fix, re-run -
  until every selected target is green or the loop is provably stuck. Trigger on
  /test-fix or when the operator asks to make the tests pass, fix the failing
  tests, or get the suite green. Portable across projects.
---

Same target discovery and selection as the `test` skill - invoke it for step 1
and step 2 rather than reimplementing the grep and the selection list. This
skill owns what happens after the first red result: the fix loop.

The contract is narrow: the code becomes correct, the tests stay honest.

## The loop

One iteration is: run -> read the failure -> one root cause -> one fix ->
re-run. Never batch several speculative fixes into one iteration; a green run
after three simultaneous changes proves nothing about which one mattered.

### Run

Run the failing target alone, not the whole selection - the fastest command
that reproduces the failure. Widen back to the full selection only when that
target is green.

### Diagnose

Read the actual error output before touching a file. Apply the `triage` skill
to reach a verified root cause; for a failure whose cause is genuinely unclear
after one look, apply `dialectic` rather than guessing twice.

Decide explicitly which side is wrong, and say so in one line before editing:

- **Code is wrong**: the test states the intended behaviour. Fix the code.
- **Test is wrong**: the test encodes an outdated or incorrect expectation.
  Fixing it is allowed *only* with a stated reason for why the old expectation
  was wrong - never because the code disagrees with it.
- **Environment is wrong**: missing dependency, stale container, absent env var,
  unbuilt artefact. Fix the environment or report it; do not patch code around
  a broken environment.

### Fix

Smallest change that addresses the root cause. Follow the project's existing
idioms and the `no-defaults` and `comments-clean` rules.

Forbidden, in every iteration, without explicit operator approval:

- deleting, skipping, `xfail`-ing, or commenting out a failing test
- loosening an assertion to whatever the code currently produces
- catching or swallowing the exception the test was written to surface
- adding retries, sleeps, or reruns to paper over a flaky failure
- disabling a linter rule, a type check, or a test target from the selection

Any of these is a report item, not a fix. A suite that is green because the
failing test no longer runs is a regression disguised as success.

### Re-run

Re-run the same target. Then, once it passes, re-run every target that was
already green - a fix that breaks a neighbouring suite is not a fix. Only
after the full selection is green is the loop done.

## Stopping

Stop and report, without asking for permission to stop:

- **Green**: full selection passes. Report and stop.
- **No progress**: the same failure survives 3 iterations, or the failure count
  stops falling across 3 iterations. Report the root cause reached so far, what
  was tried, and why each attempt failed.
- **Fix exceeds the mandate**: the real fix is an API change, a dependency bump,
  a schema migration, or a redesign. Name it, show the minimal diff it would
  need, and let the operator decide.
- **Oscillation**: fixing A re-breaks B and vice versa. Report both with the
  conflict between them - that is a design problem, not a test problem.
- **Flaky**: a target passes and fails without any change between runs. Report
  it as flaky with both outputs; never "fix" it by rerunning until green.

Never loop silently. Emit one line per iteration: target, failure, hypothesis,
change made.

## Report

- Per iteration: what failed, the root cause, the fix, the result.
- Final state of every selected target, pass or fail, with the verbatim output
  of anything still failing.
- Everything deliberately not done: tests judged wrong but left alone,
  environment issues, out-of-mandate fixes.
- The exact command reproducing the final state.

State calibrated confidence in the fixes per the `confidence` skill. Do not
commit unless the operator asked for a commit.
