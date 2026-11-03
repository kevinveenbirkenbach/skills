---
name: kvb-think-brainstorm
description: >
  Generate options through fixed lenses, then score and narrow them. Trigger
  on /kvb-think-brainstorm, "brainstorm", or when a skill needs alternatives.
---

Generate first, judge second: no option is scored before all are on the
table.

## Step 1: frame

One line: the problem, who has it, and which constraints are fixed. Ask the
operator only for what the context does not give, by the `kvb-think-listen`
skill's rules.

## Step 2: diverge

At least one option per lens, none judged yet:

- **Obvious**: what anyone would try first.
- **Minimal**: the smallest change that helps at all.
- **Maximal**: the version without a budget limit.
- **Inversion**: solve the opposite problem, or remove the need.
- **Analogy**: how another domain solves a problem of the same shape.
- **Drop a constraint**: what one fixed constraint, gone, makes possible.
- **Reuse**: what the repository, the platform or a dependency already has.

## Step 3: converge

Rate every option on value, effort and risk (`low`, `medium`, `high`),
merge duplicates, and drop each option another one beats on all three.

## Step 4: hand over

The best two or three go to the calling skill, or to the operator through
`AskUserQuestion` with `multiSelect: false`, the recommended option first.
A consequential choice runs through the `kvb-think-dialectic` skill before
it is offered.

## Output

| Option | Lens | Value | Effort | Risk | Kept |

Dropped options stay in the table with the option that beat them.
