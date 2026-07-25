---
name: no-defaults
description: >
  Forbid default values for parameters, settings, and environment lookups in
  every language. Load and apply AUTOMATICALLY on every task that writes,
  edits, generates, refactors, or reviews code, config, templates, schemas,
  or infrastructure — never wait to be asked. A default silently substitutes
  a guess for a value the caller failed to supply, so a misconfiguration
  becomes wrong behaviour instead of a loud failure. Demand strict, explicit
  values and fail loudly when one is missing. `false`, `null` and `""` are the
  only free defaults; every other default needs a written justification.
  Portable across projects.
---

A default value is a guess, written at the point where the caller's intent is
least known, and it turns a missing value into a plausible wrong answer instead
of an error. Two callers then read the same call differently: one means "use the
default", the other simply forgot. That ambiguity is the defect this rule exists
to prevent.

Never write a substantive default. Require the value. When it is absent, fail
immediately, loudly, and with a message that names the missing thing.

## The rule

1. Every parameter, option, setting, environment lookup, column, and template
   variable MUST be supplied explicitly by its caller.
2. A missing value MUST abort at the earliest possible moment — argument
   parsing, config load, container start — never at the point of use, and never
   by proceeding with a substitute.
3. The error MUST name the missing key and where to set it.
4. Optionality, when a value genuinely may be absent, MUST be modelled as an
   explicit named case that the call site handles, never as a silent
   substitution. `None`/`null` handled in a visible branch is fine; a fallback
   baked into the accessor is not.

## The empty defaults are free

`false`, `null` (`None`, `nil`, `undefined`), and the empty string `""` MAY be
used as defaults without justification. They are the one class that carries no
guess: they denote absence itself rather than inventing a value the caller might
have meant. `${VAR:-}`, `d.get(k)`, `a ?? null`, and `def f(a=None)` are fine.

Every other default value — a number, a non-empty string, a non-empty list or
map, an enum member, a path, a timeout, a retry count — MUST carry an inline
comment stating why that specific value is correct for every caller that omits
it. No comment, no default. Use whatever exception-comment form the project
sanctions; where none exists, a plain comment on or directly above the default.

The comment is the point: it forces you to name the assumption, so a reviewer
can disagree with it. "Sensible", "standard", and "usual" name nothing — if the
justification does not survive being written down, the default does not survive
either.

## Banned constructs, by language

Each `Never` below means the default is a substantive value. The same construct
with `false`, `null`, or `""` is permitted, and with any other value is permitted
only when justified in a comment.

| Language | Never | Instead |
|---|---|---|
| Bash | `${VAR:-x}`, `${VAR:=x}`, `: "${VAR:=x}"` | `: "${VAR:?set VAR in <file>}"` |
| Python | `def f(a=1)`, `d.get(k, x)`, `getattr(o, n, x)`, `os.environ.get(k, x)`, `argparse(default=)` | required args, `d[k]`, `os.environ[k]`, `add_argument(required=True)` |
| Jinja / Ansible | `\| default(x)`, `lookup('env', k) \| default('')` | `\| mandatory`, `assert` on the var |
| JS / TS | `function f(a = 1)`, `const {a = 1} = o`, `a \|\| x`, `a ?? x` | required params, explicit `if (a === undefined) throw` |
| Go | relying on zero values | constructor that validates every field |
| Rust | `unwrap_or`, `unwrap_or_default`, `#[serde(default)]` | `ok_or(Error::MissingX)?`, `#[serde(deny_unknown_fields)]` |
| Java / C# | optional parameters, `??`, `getOrDefault` | required constructor args, explicit null check that throws |
| SQL | `DEFAULT` on a column | `NOT NULL` and supply it in every insert |
| Make | `VAR ?= x` | `VAR := $(or $(VAR),$(error VAR is required))` |
| Docker / Compose | `${VAR:-x}`, `ENV` placeholders standing in for config | `${VAR:?VAR is required}` |
| Terraform / Helm | `variable { default = }`, `default` in `values.yaml` | no default; fail on the missing input |

## How to apply

Before writing any parameter, ask: what happens if the caller omits it? If the
answer is anything other than "it fails and says so", rewrite it.

While editing, treat every `default`, `?:`, `??`, `||`, `:-`, `:=`, `or`,
`fallback`, and `getOrElse` in a value-resolution position as a finding unless
its substitute is `false`, `null` or `""`, or a comment already justifies it.
Grep your own diff for them before presenting it.

Pushing a default one layer up is not a fix: a caller that passes a constant it
invented has only moved the guess. Follow the value to its true owner —
the operator, the inventory, the deployment config — and require it there.

Removing an existing default is a behaviour change. Do not do it silently as a
drive-by: name it, and let the operator decide whether it lands in this change
or its own.

## What does not count as a justification

"It is conventional", "every other project does it", "the value is obvious",
and "it keeps the signature short" justify nothing — they assert that someone
else made the choice, which is the ambiguity this rule exists to remove. A valid
justification names why this value is right for a caller who says nothing.

An operator asking for a specific default, in this conversation, for this value,
settles it without a comment.

## Penalty

If this audit finds an unjustified default you wrote yourself: say so in the
report, with file and count and no excuses; lower the confidence numbers for the affected
bundle; and write the incident to persistent agent memory, recording the date
and the construct you reached for, so the calibration survives the session.
