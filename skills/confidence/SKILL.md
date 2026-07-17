---
name: confidence
description: >
  Report calibrated confidence unprompted. Trigger whenever you stage
  changes, declare a fix or bundle ready, or summarize completed work the
  operator may commit or deploy — the operator must never have to ask "how
  sure are you?". Portable across projects.
---

Every stage summary, fix report, or ready-to-commit bundle ends with a
confidence block:

1. **Fix confidence** (percent): probability the change does what it
   claims. **Break risk** (percent): probability it breaks anything else.
   Two separate numbers, never one blended figure.
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
