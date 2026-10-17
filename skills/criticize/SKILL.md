---
name: criticize
description: >
  Look at a problem, a plan, a design, a decision, a text, or a piece of code
  critically from diverse aspects and give constructive criticism: what holds,
  what does not, why it matters, and what to do instead. Every critique point is
  hardened with the dialectic skill before it is reported. Trigger on
  /criticize, "kritisiere", "kritisch betrachten", "konstruktive Kritik",
  "was haeltst du davon", or when the operator asks for honest feedback on
  something rather than for a fix. Portable across projects.
---

The stance is critical but constructive: the goal is a better result, not a
verdict on its author. This skill judges any artifact from many angles; it is
not limited to code (`sceptic` hunts violated engineering principles in code,
`code-review` hunts bugs). Read-only: report the critique, change nothing
unless the operator asks afterwards.

## Before you start: listen

Invoke the `active-listening` skill. Pin down what is being criticized, what it
is meant to achieve, for whom, and under which constraints. Derive what you can
from the artifact and its surroundings first; ask only what only the operator
knows. A critique against the wrong goal is noise.

## Steelman first

Restate the artifact and its intent in its strongest form, in two or three
sentences. Criticize that version, never a weaker one you made up. If you cannot
steelman it, you have not understood it yet; go back to listening.

## The aspects

Sweep every aspect that applies, and name the ones you skipped and why:

1. **Goal fit** - does it solve the stated problem for the stated audience, or
   a neighbouring one?
2. **Correctness** - are the facts, the logic, and the claimed cause-effect
   chains right? Which claim lacks evidence?
3. **Completeness** - missing cases, missing stakeholders, missing failure
   paths, missing definition of done.
4. **Consistency** - contradictions inside the artifact or against its
   neighbours; the same truth stated twice in two versions.
5. **Simplicity** - mechanism, scope, or wording the problem never asked for;
   the smaller design that does the same.
6. **Feasibility and cost** - effort, dependencies, order of steps, what blocks
   what, what it costs to run and to maintain.
7. **Risk** - security at trust boundaries, data loss, reversibility, blast
   radius, what happens when it fails halfway.
8. **People** - usability, accessibility, the reader's or user's actual path,
   who gains, who carries the burden.
9. **Alternatives** - at least one materially different approach, compared
   honestly on the aspects above.
10. **Ethics and compliance** - only where it touches personal data, licences,
    law, or fairness.

## Harden every point with dialectic

Run each candidate critique through the `dialectic` skill before reporting it:

- **Thesis**: the critique point with its evidence.
- **Antithesis**: independent defenders argue that the artifact is right as it
  is, or that the constraint behind it is real; independent skeptics attack the
  suggested improvement for new problems it would cause.
- **Synthesis**: keep the point, refine it, or drop it.

Batch minor points into one dialectic round; run consequential points (high
severity, expensive to act on, or challenging a premise) one by one.

## Output

One line of scope, then the steelman. Then:

- **Keep**: up to three strengths that must survive any change.
- **Critique**: one ranked table, highest impact first:

| Severity | Aspect | Observation | Why it matters | Suggestion | Evidence |

`Evidence` is `proven` (read, run, reproduced, cited) or `derived` (reasoned).

Close with at most three lines: how many candidate points dialectic dropped and
why, the single change that helps most, and the `confidence` skill's numbers for
the critique as a whole.

## Rules

- Every critique carries a concrete suggestion. A complaint without one becomes
  an open question or is dropped.
- Criticize the work, never the person. Direct wording, no sarcasm, no
  softening of a real problem, no inflation of a minor one.
- A point that attacks a stated constraint or goal is labelled "challenges a
  premise" and kept apart from points that work within it.
- No taste or formatting nitpicks unless the operator asks for them.
- Answer in the operator's language.
- The critique ends at the report. Do not fix, stage, or rewrite as part of
  this skill.
