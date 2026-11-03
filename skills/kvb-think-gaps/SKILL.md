---
name: kvb-think-gaps
description: >
  Find and rank missing work (structural flaws, missing features); each pick
  goes to kvb-create-requirement. Trigger on /kvb-think-gaps, "was fehlt
  noch", or asked what to build next.
---

Two blind spots produce different work: the code has defects of structure,
the product has gaps of use. This skill runs both lenses, ranks what comes
out, and lets the operator choose. It writes no file; the
`kvb-create-requirement` skill writes the requirement for every pick.

## Step 1: fix the scope

Name the target in one line: repository, subsystem, role, or user-facing
surface. Read the project's existing requirement documents first; an
already-written requirement is not a finding.

## Step 2: the principles pass

Invoke the `kvb-check-principles` skill on the target. Its findings become requirement
candidates by severity: a violated SPOT, SRP, or trust boundary is work the
product needs whether or not a user ever notices. Carry each finding's
`file:line` evidence forward — a requirement without it is a guess.

## Step 3: the usability pass

Independently, look for what the product does not do yet. Anchor every gap
in something observable in the repository, never in an invented persona:

- **Entry** — can someone install, configure, and run it without reading the
  source? Missing `--help`, missing example config, an undocumented required
  variable.
- **Recovery** — does a failure tell the user what to do next? Errors that
  print a stack trace instead of the remediation, no dry-run, no way to undo
  or uninstall, no idempotent re-run.
- **Feedback** — does a long operation say anything while it works? Silent
  minutes, no progress, no exit summary.
- **Empty and edge states** — first run with no data, zero results, an
  expired credential, a partially completed run.
- **Discoverability** — a capability that exists but nothing surfaces:
  undocumented flags, features reachable only by reading tests.
- **Accessibility and locale** — output that assumes colour, a terminal
  width, or one language.

Each gap gets one line: `observed evidence -> who is blocked -> smallest
change that unblocks them`. Drop anything you cannot anchor.

## Step 4: rank and ask

Merge both lists, drop duplicates where a structural finding and a usability
gap describe the same defect, and rank by blocked users first, blast radius
second.

Then apply `kvb-think-listen`: answer everything you can from the code, the
docs, and the git history yourself, and put only the genuinely open decisions
to the operator with `AskUserQuestion`, `multiSelect: false`, so every
question renders as radio buttons. At most four questions per call, each
option a real alternative — never one option plus filler:

1. **Which candidates** become requirements this run, ranked, each option
   carrying its evidence in the description.
2. **Which shape** the chosen one takes — for a feature typically
   `Minimal version that unblocks the user`, `Full version`, `Fix the
   underlying structure instead`, `Document the limitation and defer`.

Never assume an answer and never fold two decisions into one option.

## Step 5: hand over

Run the `kvb-create-requirement` skill once per chosen candidate. Its
context step starts from the candidate's evidence and chosen shape; the
rejected shapes go into its Decisions section.

## Rules

- Findings only: no file, no implementation, no refactor, no staging as
  part of this skill.
- Every candidate traces to evidence — a `file:line`, a failing path, a
  missing artifact. A candidate whose justification is "would be nice" is
  dropped.
- Close with the `kvb-check-confidence` skill's numbers for the analysis: how sure the
  gaps are real, and what the passes did not cover.
