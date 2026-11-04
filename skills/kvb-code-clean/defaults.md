# Judging defaults

Step 2 of the `kvb-code-clean` skill reads this file when `defaults.py`
reports hits or a review needs the whole rule.

A default is a guess written where the caller's intent is least known: it
turns a missing value into a plausible wrong answer, and two callers read the
same call differently (one means "use the default", the other forgot).

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

## Judge each hit

- **Real default**: rewrite it as the printed replacement, at the value's
  true owner.
- **Justified**: a `justified?` hit stays only if its comment meets the bar
  above.
- **False positive**: a `candidate` (`??`, `||`, Python `or`) that is logic,
  or no default at all; report why.

## What the script cannot see

Go fields left to zero values (a constructor validating every field),
defaults in a Helm `values.yaml` (none; fail on the missing input), Docker
`ENV` placeholders for config (`${VAR:?VAR is required}`), Java overloads
filling an optional parameter (required constructor arguments), and any other
value-resolution fallback (`?:`, `getOrElse`, `fallback`, a dataclass field).

## How to apply

- Before writing any parameter, ask what happens if the caller omits it;
  anything but "it fails and says so" gets rewritten.
- Pushing a default one layer up is no fix: a caller passing an invented
  constant only moved the guess. Require the value at its true owner
  (operator, inventory, deployment config).
- Removing an existing default is a behaviour change, never a silent
  drive-by: name it and let the operator decide whether it lands in this
  change or its own.
