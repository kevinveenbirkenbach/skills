---
name: kvb-check-break-risk
description: >
  Derive the break-risk percentage from measurement, not feel, for every
  `kvb-check-confidence` report; also on "what could this break?" or a named
  break-risk threshold.
---

Break risk is the probability the change breaks something it did not intend
to touch; without these steps a number is a guess.

## Fast path

Only documentation, comments, or tests that ran green with it: name the
files (`git diff --cached --name-only`), report under 1%, skip the method.

## The method

1. **Consumers**: enumerate and count them in `HEAD` (`git grep <symbol>
   HEAD`), the code graph first.
2. **Delta**: old against new on today's inputs, at the surface.
3. **Live or latent** per finding.
4. **Matrix**: a verdict per deployment axis.
5. **Failure mode**: closed or open.
6. **Evidence**: executed, negative-controlled.

Read `reference.md` next to this file for the steps and anchors,
`${CLAUDE_SKILL_DIR}/../kvb-check-confidence/chain.md` before reporting.

## When the operator names a threshold

It gates the work: get the cheapest evidence closing the gap, re-measure;
report a miss only when that evidence is out of reach, naming it.
