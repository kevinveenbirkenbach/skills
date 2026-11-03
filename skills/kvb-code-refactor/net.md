# Refactor: no test covers the change set

- **Testable logic**: write characterization tests first, against the
  current behaviour, including the behaviour you consider wrong, so the
  refactor cannot silently change it. Keep them small and framework-free
  unless the project already has a framework. Fix the captured wrongness in
  a separate change, never in this one.
- **Not sensibly testable**: pure glue, declarative config, a thin wrapper
  over a service the test would have to mock into meaninglessness, or a
  project with no test setup at all. Say so in one line and refactor without
  a net; do not invent a test harness the project never asked for.

The new tests are part of the deliverable and must still pass unchanged
after the refactor. A test that had to be edited to stay green means the
behaviour moved: revert the refactor, not the test.
