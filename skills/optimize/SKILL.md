---
name: optimize
description: >
  The shared objective of the self-improving skills: raise efficiency — fewer
  tokens, less time — and raise quality at the same time. Trigger from autotune,
  autoskill and confidence, which route their objective here, and on /optimize
  when the operator asks how to make the agent's own work cheaper, faster or
  better. Portable across projects.
---

Every skill, rule, or report the agent produces about its own working is judged
on three axes at once. A proposal that cannot name the axis it moves is not an
optimization, it is a preference.

## The three axes

- **Tokens** — fewer input and output tokens for the same result: read the range
  instead of the whole file, grep the saved log instead of re-running the
  command, route to an authoritative doc instead of duplicating it, report in
  lines instead of paragraphs.
- **Time** — fewer round trips and less waiting: independent calls in parallel,
  one command that answers the question instead of three that circle it, no
  polling for work the harness will report on its own.
- **Quality** — fewer errors and less rework: verification instead of
  assumption, and learnings that persist so the same mistake is not paid for
  twice.

## Rules

- A change must improve at least one axis and damage none. Output that got
  cheaper but lost correctness is a regression, not an optimization.
- Quality is never the currency: validation, error handling, tests, and security
  steps are not what gets cut to save tokens or time.
- Measure, do not guess: name the observed friction — the re-read, the retry,
  the correction the operator had to give twice — and what it cost. A guessed
  percentage is not a measurement.
- The cheapest step is the one that does not run: drop work before optimizing
  it.
- Persist it or pay again: an optimization that lives only in this session is
  re-derived in the next one, so it belongs in a skill or a memory entry.
