---
name: kvb-code-no-defaults
description: >
  Forbid default values for parameters, settings and environment lookups;
  demand explicit values. Apply AUTOMATICALLY whenever code, config,
  templates or infrastructure are written, edited or reviewed.
---

A default is a guess written where the caller's intent is least known: it
turns a missing value into a plausible wrong answer instead of an error, and
two callers read the same call differently (one means "use the default", the
other forgot). Never write a substantive default: require the value, and when
it is absent fail immediately, loudly, naming the missing thing.

## The rule

1. Every parameter, option, setting, environment lookup, column and template
   variable MUST be supplied explicitly by its caller.
2. A missing value MUST abort at the earliest moment (argument parsing,
   config load, container start), never at the point of use and never by
   proceeding with a substitute.
3. The error MUST name the missing key and where to set it.
4. Genuine optionality MUST be an explicit named case the call site handles,
   never a silent substitution: `None`/`null` in a visible branch is fine, a
   fallback baked into the accessor is not.

## Free and justified defaults

`false`, `null` (`None`, `nil`, `undefined`) and `""` MAY be defaults without
justification: they denote absence itself, not a guessed value. `${VAR:-}`,
`d.get(k)`, `a ?? null` and `def f(a=None)` are fine.

Every other default (a number, a non-empty string, list or map, an enum
member, a path, a timeout, a retry count) MUST carry an inline comment saying
why that specific value is right for every caller that omits it; no comment,
no default. Use the project's sanctioned exception-comment form, else a plain
comment on or directly above the default. The comment names the assumption
so a reviewer can disagree with it.

"Sensible", "standard", "usual", "it is conventional", "every other project
does it", "the value is obvious" and "it keeps the signature short" justify
nothing: they assert someone else made the choice. A valid justification
names why this value is right for a caller who says nothing. The operator
asking for a specific default, in this conversation, for this value, settles
it without a comment.

## How to apply

- Before writing any parameter, ask what happens if the caller omits it;
  anything but "it fails and says so" gets rewritten.
- While editing, treat every `default`, `?:`, `??`, `||`, `:-`, `:=`, `or`,
  `fallback` and `getOrElse` in a value-resolution position as a finding
  unless its substitute is `false`, `null` or `""` or a comment justifies it.
  Grep your own diff for them before presenting it.
- Read `constructs.md` next to this file for a language's banned forms and
  their replacements before rewriting a default there.
- Pushing a default one layer up is no fix: a caller passing a constant it
  invented only moved the guess. Follow the value to its true owner (the
  operator, the inventory, the deployment config) and require it there.
- Removing an existing default is a behaviour change, never a silent
  drive-by: name it and let the operator decide whether it lands in this
  change or its own.

## Penalty

An unjustified default you wrote yourself: say so in the report with file and
count and no excuses, lower the confidence numbers for the affected bundle,
and write the incident with the date and the construct you reached for to
persistent agent memory, so the calibration survives the session.
