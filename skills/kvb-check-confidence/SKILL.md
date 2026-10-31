---
name: kvb-check-confidence
description: >
  Report calibrated fix confidence and break risk unprompted whenever you
  stage changes, declare a fix or bundle ready, or summarize work the operator
  may commit or deploy.
---

Every stage summary, fix report, or ready-to-commit bundle ends with a
confidence block.

Invoke the `kvb-check-break-risk` skill every time, before writing the block; this skill
reports the number it derives and never estimates one itself.

1. **Fix confidence** (percent): probability the change does what it
   claims. **Break risk** (percent): probability it breaks anything else,
   derived via the `kvb-check-break-risk` skill. Two separate numbers, never one
   blended figure.
2. **Evidence**: the strongest proof lines only — what was executed,
   reproduced, enumerated, or read from authoritative source. Distinguish
   proven (ran it, saw it) from derived (reasoned statically).
3. **Residuals**: name exactly what keeps the number below 100 and what
   would close the gap (live deploy, missing artifact, unexercised path).
   Never a bare percentage without its residuals.

Calibration rules:

- Number the claim you verified, not the effort you spent; discount after
  any error the operator caught in the same area.
- Distinguish "fixes the observed failure" from "makes the job green" when
  hidden layers may follow, and give both numbers.
- Static analysis alone caps at the low nineties; only executed evidence
  (test, reproduction, live probe) justifies more.

A threshold the operator named ("95% confidence, break risk ≤5%") is a gate on
the work, handled as the `kvb-check-break-risk` skill's last section says, for both
numbers.

Objective: the `kvb-skills-tune` skill's **Objective** section. Two figures with their residuals replace a
hedging paragraph and save the operator a verification round trip.
