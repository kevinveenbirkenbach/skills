# Fix mode

The contract is narrow: the code becomes correct, the tests stay honest.

One iteration is: run -> read the failure -> one root cause -> one fix ->
re-run. Never batch several speculative fixes into one iteration; a green run
after three simultaneous changes proves nothing about which one mattered.

- **Run** the failing target alone, the fastest command that reproduces the
  failure. Widen back to the full selection only when that target is green.
- **Diagnose** from the actual error output before touching a file. Locate
  the code through the codebase-memory-mcp graph first (`search_graph`,
  `trace_path`, `get_architecture`; the `kvb-agent-optimize` skill sets it
  up), grep and read after. Apply the `kvb-ci-triage` skill to reach a
  verified root cause; for a cause still unclear after one look, apply
  `kvb-think-dialectic` rather than guessing twice. Say in one line which side
  is wrong:
  - **Code**: the test states the intended behaviour. Fix the code.
  - **Test**: it encodes an outdated or incorrect expectation. Fix it only with
    a stated reason why the old expectation was wrong, never because the code
    disagrees with it.
  - **Environment**: missing dependency, stale container, absent env var,
    unbuilt artefact. Fix the environment or report it; do not patch code
    around it.
- **Fix** with the smallest change that addresses the root cause, in the
  project's idioms and under the `kvb-code-no-defaults` and
  `kvb-code-no-comments` rules. Forbidden without explicit operator approval:
  deleting, skipping, `xfail`-ing or commenting out a failing test; loosening
  an assertion to what the code produces; swallowing the exception the test
  surfaces; retries, sleeps or reruns over a flaky failure; disabling a linter
  rule, a type check or a target. Any of these is a report item, not a fix: a
  suite that is green because the failing test no longer runs is a regression
  disguised as success.
- **Re-run** the same target, then every target that was already green; only
  a full green selection ends the loop. Every re-run is admitted like the
  first run (Step 3 of `SKILL.md`).

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
reproducing the final state. State confidence per the `kvb-check-confidence`
skill. Do not commit unless the operator asked for a commit.
