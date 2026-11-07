---
name: kvb-check-break-risk
description: >
  Derive the break-risk percentage from measurement, not feel, for every
  `kvb-check-confidence` report; also on "what could this break?" or a named
  break-risk threshold.
---

Break risk is the probability the change breaks something it did not intend to
touch: not the inverse of fix confidence, not a mood. Derive it by the steps
below; without them a number is a guess.

## Fast path

A change whose files nothing builds, deploys, or runs (documentation and
comments only, or tests that ran green with it) has no consumers outside
itself. Name the files (`git diff --cached --name-only`), report break risk
under 1%, and skip the method. Any other file takes the full method.

## The method

1. **Consumers**: enumerate every consumer of everything the change alters, in
   the committed state (`git grep <symbol> HEAD`) and of its output; say the
   count. A caveat never licenses a low number; an enumeration does. Query
   the codebase-memory-mcp graph first (`detect_changes`, `trace_path`,
   `search_graph`; the `kvb-agent-optimize` skill sets it up), grep and read
   after.
2. **Delta**: run the old and the new code on today's inputs and compare at
   the surface where the difference shows (rendered output, emitted config,
   returned set, wire bytes), not as the source reads.
3. **Live or latent**: per finding, whether a shipped configuration reaches it.
   Only live findings move the number materially.
4. **Matrix**: a verdict per deployment axis the project has, never averaged.
5. **Failure mode**: fails closed and loud, or open and silent; the latter can
   outrank a likelier failure.
6. **Evidence**: executed beats derived; a report, a summary or your own
   earlier message is not evidence; negative-control every check you cite,
   including one you did not write.

`reference.md` next to this file explains each step with the trap it defeats.
Read it when a step is new to you or its result is contested.

## Producing the number

State it as a percentage next to fix confidence, never blended, and always with
its residuals; `kvb-check-confidence` passes it to the `kvb-check-score` block
as `--break`. Anchor roughly:

- **Under 5%**: consumers enumerated, delta measured at the surface, every axis
  of the matrix covered by executed evidence, failure mode closed.
- **5 to 15%**: measured, but one axis or one layer rests on reasoning: no live
  run, a mode not exercised, a runtime the render cannot prove.
- **15 to 40%**: a real behaviour change whose consumers are enumerated but
  whose effect is unmeasured, or a latent finding with a plausible trigger.
- **Above 40%**: a known live defect, an unenumerated consumer set, or a
  fail-open exposure without a verified control. Fix it rather than report it.

Discount yourself after any error the operator caught in the same area during
this session, and say that you are doing so. A region where you have already
been wrong twice deserves a worse number than its paper evidence suggests.

## When the operator names a threshold

A named threshold is a gate on the work, not a field in the report. Missing it
is a work item: name the cheapest evidence that would close the gap, go get it,
re-measure. Report a miss only when the evidence is genuinely out of reach, and
name which piece.
