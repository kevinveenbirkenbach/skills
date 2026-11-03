---
name: kvb-think-criticize
description: >
  Constructive criticism of a plan, design, decision, text or code, each
  point hardened by dialectic. Trigger on "kritisiere",
  "konstruktive Kritik", "was haeltst du davon", or requests for honest
  feedback.
---

Critical but constructive: the goal is a better result, not a verdict on its
author. Any artifact, from many angles (`kvb-check-principles` hunts violated
engineering principles in code, `code-review` hunts bugs). Read-only: the
critique ends at the report; fix, stage or rewrite nothing unless the operator
asks afterwards.

## Before you start: listen

Invoke the `kvb-think-listen` skill: what is criticized, what it should
achieve, for whom, under which constraints. Derive what you can from the
artifact and its surroundings first (code through the codebase-memory-mcp
graph: `search_graph`, `trace_path`, `get_architecture`, set up by the
`kvb-agent-optimize` skill; grep and read after); ask only what only the
operator knows. A critique against the wrong goal is noise.

## Steelman first

Restate the artifact and its intent at their strongest in two or three
sentences; criticize that version, never a weaker one. If you cannot
steelman it, you have not understood it; go back to listening.

## The aspects

Sweep every applicable aspect; name skipped ones and why:

1. **Goal fit**: the stated problem for the stated audience, or a neighbour?
2. **Correctness**: facts, logic, claimed cause-effect chains; which claim
   lacks evidence?
3. **Completeness**: missing cases, stakeholders, failure paths, definition of
   done.
4. **Consistency**: contradictions inside the artifact or against its
   neighbours; one truth stated twice in two versions.
5. **Simplicity**: mechanism, scope or wording the problem never asked for;
   the smaller design that does the same.
6. **Feasibility and cost**: effort, dependencies, step order, what blocks
   what, running and maintenance cost.
7. **Risk**: security at trust boundaries, data loss, reversibility, blast
   radius, failure halfway.
8. **People**: usability, accessibility, the reader's or user's actual path,
   who gains, who carries the burden.
9. **Alternatives**: at least one materially different approach, compared
   honestly on the aspects above.
10. **Ethics and compliance**: only where personal data, licences, law or
    fairness are touched.

## Harden every point with dialectic

Run each candidate through the `kvb-think-dialectic` skill before reporting:

- **Thesis**: the point with its evidence.
- **Antithesis**: independent defenders argue the artifact is right or the
  constraint behind it is real; independent skeptics attack the suggestion
  for new problems it would cause.
- **Synthesis**: keep, refine or drop.

Batch minor points into one round; run consequential ones (high severity,
expensive to act on, or challenging a premise) one by one. Scale defenders and
skeptics to the stakes; each brief names exact files or passages and the
claim, and caps the answer at five lines.

## Output

One line of scope, then the steelman. Then:

- **Keep**: up to three strengths that must survive any change.
- **Critique**: one ranked table, highest impact first:

| Severity | Aspect | Observation | Why it matters | Suggestion | Evidence |

`Evidence` is `proven` (read, run, reproduced, cited) or `derived` (reasoned).

Close with at most three lines: how many points dialectic dropped and why, the
single change that helps most, and the `kvb-check-confidence` skill's numbers
for the whole critique.

## Rules

- Every critique carries a concrete suggestion; without one it becomes an open
  question or is dropped.
- Criticize the work, never the person: direct wording, no sarcasm, no
  softening of a real problem, no inflation of a minor one.
- A point attacking a stated constraint or goal is labelled "challenges a
  premise" and kept apart from points within it.
- No taste or formatting nitpicks unless asked.
- Answer in the operator's language.
