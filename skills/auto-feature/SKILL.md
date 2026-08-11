---
name: auto-feature
description: >
  Derive the missing work of a codebase and turn it into requirement
  documents: a sceptic pass for what the code gets structurally wrong, a
  usability pass for what the product does not do yet, then active-listening
  to confirm every proposal through single-select (radio button) questions
  before anything is written. Trigger on /auto-feature, "was fehlt noch",
  "welche features brauchen wir", or when the operator asks what to build
  next. Portable across projects.
---

Two blind spots produce different work: the code has defects of structure,
the product has gaps of use. This skill runs both lenses, ranks what comes
out, and lets the operator choose — it writes requirement documents, never
implementations.

## Step 1: fix the scope

Name the target in one line: repository, subsystem, role, or user-facing
surface. Read the project's existing requirement documents first — their
location, filename convention, and section structure are the template, and
an already-written requirement is not a finding.

## Step 2: the sceptic pass

Invoke the `sceptic` skill on the target. Its findings become requirement
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

Then apply `active-listening`: answer everything you can from the code, the
docs, and the git history yourself, and put only the genuinely open decisions
to the operator with `AskUserQuestion`, `multiSelect: false`, so every
question renders as radio buttons. At most four questions per call, each
option a real alternative — never one option plus filler:

1. **Which candidates** become requirements this run, ranked, each option
   carrying its evidence in the description.
2. **Which shape** the chosen one takes — for a feature typically
   `Minimal version that unblocks the user`, `Full version`, `Fix the
   underlying structure instead`, `Document the limitation and defer`.
3. **Scope boundary** — what is explicitly out of scope, when the candidate
   could grow in more than one direction.
4. **Placement** — which requirement file or directory receives it, when the
   project has more than one.

Never assume an answer, never fold two decisions into one option, and never
write a file before the answers are in.

## Step 5: write the requirements

One document per feature — a requirement that needs "and" in its title is
two requirements. Follow the project's existing template; when there is
none, keep it to: problem with its evidence, the decided scope and its
boundary, definition of done as checkable criteria, and the alternatives the
operator rejected with the reason.

Show the drafted document and ask for a final `Write it` / `Revise it` /
`Discard` before touching disk.

## Rules

- Requirements only: no implementation, no refactor, no staging as part of
  this skill.
- Every requirement traces to evidence — a `file:line`, a failing path, a
  missing artifact. A requirement whose justification is "would be nice" is
  not written.
- Record the rejected alternatives inside the document; the next reader
  needs to know what was already considered and dismissed.
- Close with the `confidence` skill's numbers for the analysis: how sure the
  gaps are real, and what the passes did not cover.
