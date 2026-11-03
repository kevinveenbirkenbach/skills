---
name: kvb-code-no-defaults
description: >
  Forbid default values for parameters, settings and environment lookups;
  demand explicit values. Apply AUTOMATICALLY whenever code, config,
  templates or infrastructure are written, edited or reviewed.
---

A default is a guess written where the caller's intent is least known: it
turns a missing value into a plausible wrong answer, and two callers read the
same call differently (one means "use the default", the other forgot). Never
write a substantive default: require the value; when it is absent, fail at
once and loudly, naming the missing thing.

## The rule

1. Every parameter, option, setting, environment lookup, column and template
   variable MUST be supplied explicitly by its caller.
2. A missing value MUST abort at the earliest moment (argument parsing,
   config load, container start), never at the point of use and never by
   proceeding with a substitute.
3. The error MUST name the missing key and where to set it.
4. Genuine optionality MUST be an explicit named case the call site handles:
   `None`/`null` in a visible branch is fine, a fallback baked into the
   accessor is not.

## Free and justified defaults

`false`, `null` (`None`, `nil`, `undefined`), `""` and an empty list or map
MAY be defaults without justification: they denote absence, not a guessed
value. `${VAR:-}`, `d.get(k)`, `a ?? null` and `def f(a=None)` are fine.

Every other default (a number, a non-empty string, list or map, an enum
member, a path, a timeout) MUST carry a comment on or directly above it, in
the project's exception-comment form if it has one, saying why that value is
right for every caller that omits it; no comment, no default. The comment
names the assumption so a reviewer can disagree.

"Sensible", "standard", "usual", "conventional", "every other project does
it", "obvious" and "keeps the signature short" justify nothing: they assert
someone else chose. A valid justification names why this value is right for
a caller who says nothing. The operator asking for a specific default, in
this conversation, for this value, settles it without a comment.

## Detect

Before presenting a diff or a review, run
`${CLAUDE_SKILL_DIR}/scripts/defaults.py --repo <dir>` (`--staged`: index
only; `--file <path>`: a whole untracked file). Each hit prints `file:line`,
language, construct and replacement; exit 1 means hits. Judge each:

- **Real default**: rewrite it as the replacement, at the value's true owner.
- **Justified**: a `justified?` hit stays only if its comment meets the bar
  above.
- **False positive**: a `candidate` (`??`, `||`, Python `or`) that is logic,
  or no default at all; report why.

Check by hand what the script cannot see: Go fields left to zero values (a
constructor validating every field), defaults in a Helm `values.yaml` (none;
fail on the missing input), Docker `ENV` placeholders for config
(`${VAR:?VAR is required}`), Java overloads filling an optional parameter
(required constructor arguments), and any other value-resolution fallback
(`?:`, `getOrElse`, `fallback`, a dataclass field).

## How to apply

- Before writing any parameter, ask what happens if the caller omits it;
  anything but "it fails and says so" gets rewritten.
- Pushing a default one layer up is no fix: a caller passing an invented
  constant only moved the guess. Require the value at its true owner
  (operator, inventory, deployment config).
- Removing an existing default is a behaviour change, never a silent
  drive-by: name it and let the operator decide whether it lands in this
  change or its own.

## Penalty

An unjustified default you wrote: report it with file and count, no excuses;
lower the bundle's confidence numbers; write the date and the construct to
persistent agent memory so the calibration survives the session.
