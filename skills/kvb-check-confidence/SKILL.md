---
name: kvb-check-confidence
description: >
  Report calibrated fix confidence and break risk unprompted whenever you
  stage changes, declare a fix or bundle ready, or summarize committable or
  deployable work.
---

Every stage summary, fix report, or ready-to-commit bundle ends with the
score block of the `kvb-check-score` skill. Invoke the `kvb-check-break-risk`
skill every time before writing it; this skill reports the number it derives
and never estimates one itself.

1. **Fix confidence** (percent): probability the change does what it claims.
   **Break risk** (percent): probability it breaks anything else, from the
   `kvb-check-break-risk` skill. Two numbers, never one blended figure.
2. **Score**: pass both, with cost from the `kvb-check-efficiency`
   skill, time from the `kvb-check-speed` skill and security and the
   critical count from `security.py` of the `kvb-check-security` skill, to
   `${CLAUDE_SKILL_DIR}/../kvb-check-score/scripts/score.py --fix <n> --break
   <n> --efficiency <n|-> --speed <n|-> --security <n|~n> --critical <count>`
   and show its score line and gate line verbatim. Exit 4 forbids the commit
   (critical finding); exit 1 fails the 90/5 rule; exit 3 means ask the
   operator again before the commit, naming the causes the gate line prints.
3. **Evidence**: the strongest proof lines only: what was executed,
   reproduced, enumerated, or read from an authoritative source. Mark proven
   (ran it, saw it) apart from derived (reasoned statically).
4. **Residuals**: exactly what keeps the number below 100 and what would
   close the gap (live deploy, missing artifact, unexercised path). Never a
   bare percentage without its residuals.

Calibration rules:

- Number the claim you verified, not the effort you spent; discount after
  any error the operator caught in the same area.
- Distinguish "fixes the observed failure" from "makes the job green" when
  hidden layers may follow, and give both numbers.
- Static analysis alone caps at the low nineties; only executed evidence
  (test, reproduction, live probe) justifies more.

A threshold the operator named ("95% confidence, break risk ≤5%") is a gate on
the work for both numbers, handled as the `kvb-check-break-risk` skill's last
section says. 90/5 also needs `gate: green` from `gate.py status` of the
`kvb-check-gate` skill, which states the rule and its residuals.

Objective: the `kvb-skill-tune` skill's **Objective** section. Two figures
with their residuals replace a hedging paragraph and save the operator a
verification round trip.
