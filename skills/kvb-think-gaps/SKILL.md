---
name: kvb-think-gaps
description: >
  Find and rank missing work (structural flaws, missing features); each pick
  goes to kvb-create-requirement. Trigger on "was fehlt noch" or when asked
  what to build next.
---

The code has defects of structure, the product has gaps of use. This skill
runs both lenses, ranks the result and lets the operator choose. It writes no
file; the `kvb-create-requirement` skill writes the requirement for every
pick.

## Step 1: fix the scope

Name the target in one line: repository, subsystem, role or user-facing
surface. Read the project's existing requirement documents first; an
already-written requirement is not a finding. Explore through the
codebase-memory-mcp graph first (`search_graph`, `trace_path`,
`get_architecture`, `detect_changes`; the `kvb-agent-optimize` skill sets it
up), grep and read after.

## Step 2: the principles pass

Invoke the `kvb-check-principles` skill on the target. Its findings become
requirement candidates by severity: a violated SPOT, SRP or trust boundary is
work the product needs whether or not a user notices. Carry each finding's
`file:line` forward; a requirement without it is a guess.

## Step 3: the usability pass

Independently, look for what the product does not do yet. Anchor every gap in
something observable in the repository, never in an invented persona:

- **Entry**: install, configure and run without reading the source? Missing
  `--help`, example config, an undocumented required variable.
- **Recovery**: does a failure say what to do next? A stack trace instead of
  the remediation, no dry-run, no undo or uninstall, no idempotent re-run.
- **Feedback**: does a long operation report while it works? Silent minutes,
  no progress, no exit summary.
- **Empty and edge states**: first run with no data, zero results, an expired
  credential, a partially completed run.
- **Discoverability**: a capability nothing surfaces: undocumented flags,
  features reachable only by reading tests.
- **Accessibility and locale**: output that assumes colour, a terminal width
  or one language.

Each gap gets one line: `observed evidence -> who is blocked -> smallest
change that unblocks them`. Drop anything you cannot anchor.

## Step 4: rank and ask

Merge both lists, drop duplicates where a structural finding and a usability
gap describe the same defect, and rank by blocked users first, blast radius
second.

Then apply `kvb-think-listen`: answer what you can from the code, docs and
git history yourself, and put only the genuinely open decisions to the
operator with `AskUserQuestion`, `multiSelect: false` (radio buttons), at most
four questions per call, each option a real alternative, never one option
plus filler:

1. **Which candidates** become requirements this run, ranked, each option
   carrying its evidence in the description.
2. **Which shape** the chosen one takes; for a feature typically `Minimal
   version that unblocks the user`, `Full version`, `Fix the underlying
   structure instead`, `Document the limitation and defer`.

Never assume an answer and never fold two decisions into one option.

## Step 5: hand over

Run the `kvb-create-requirement` skill once per chosen candidate. Its context
step starts from the candidate's evidence and chosen shape; the rejected
shapes go into its Decisions section.

## Rules

- Findings only: no file, implementation, refactor or staging in this skill.
- Every candidate traces to evidence: a `file:line`, a failing path, a
  missing artifact. "Would be nice" is dropped.
- Close with the `kvb-check-confidence` skill's numbers for the analysis: how
  sure the gaps are real, and what the passes did not cover.
