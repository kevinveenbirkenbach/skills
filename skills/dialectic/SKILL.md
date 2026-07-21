---
name: dialectic
description: >
  Reach a defensible conclusion through a dialectical process — thesis,
  adversarial antithesis, synthesis — iterated until one thesis survives every
  attack at ~99% confidence. Trigger for any consequential root-cause, design,
  or decision where being wrong is expensive and the answer is not yet certain.
  Deep-inspects every accessible source. Portable across projects.
---

Reach the truth by dialectic, not by first guess. Do not stop at a plausible
answer; drive the loop until a thesis survives every attack at ~99% confidence.

## Before you start: listen

Invoke the `active-listening` skill first. Do not begin the dialectic until you
have gathered every requirement, constraint, and success criterion the task
needs. A dialectic run on the wrong question wastes the whole loop. Return to
`active-listening` mid-loop whenever an objection turns on a fact only the
operator holds.

## The loop

1. **Thesis.** Form the strongest initial claim you can, grounded in evidence,
   not assumption. Deep-inspect every source you can reach: the source code and
   git history; the running containers (exec, logs, inspect through whatever
   make or CLI helpers the project exposes); CI logs and artifacts; tests; docs.
   Cite `file:line` and command output — never a bare assertion.
2. **Antithesis.** Spawn MULTIPLE independent skeptics (parallel subagents or a
   workflow) whose only job is to REFUTE the thesis. Each re-inspects the
   sources itself and defaults to "refuted" on any concrete hole. Give diverse
   skeptics diverse lenses: correctness, an alternate mechanism, does-it-
   reproduce, does-the-fix-break-something-else.
3. **Synthesis.** Fold every surviving objection back into a refined thesis. A
   skeptic that found a real hole replaces or corrects the thesis; a skeptic
   that failed to refute raises confidence.
4. **Iterate.** Repeat thesis → antithesis → synthesis until a full skeptic
   round finds no new hole and the thesis holds at ~99%. If confidence stalls
   below 99%, name the exact residual and the evidence that would close it, then
   go get that evidence (more inspection, or `active-listening` for an
   operator-only fact) and loop again.

## Rules

- Executed evidence beats reasoning: run it, exec into it, read the log. A
  thesis backed only by static reasoning caps in the low nineties.
- The antithesis MUST be independent — never let the thesis-author be its own
  sole skeptic.
- Diversity over redundancy: skeptics with different lenses catch failure modes
  identical skeptics miss.
- Report the final thesis with its evidence AND the losing objections, so the
  operator sees why it survived.
