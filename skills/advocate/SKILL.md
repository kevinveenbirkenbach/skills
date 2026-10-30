---
name: advocate
description: >
  Check a commit for legal soundness before it lands: is the project licence
  compatible with the code and dependencies the change brings in, are the
  attribution duties met, is copied code traceable, does the change touch
  personal data (GDPR) or third-party trademarks. Run AUTOMATICALLY, without
  being asked, every time the operator requests a commit in any wording,
  BEFORE executing that request; also on /advocate [ref|range], "rechtlich
  prüfen", "lizenz prüfen", or when the operator asks whether a change is
  legally clean. Portable across projects.
---

The stance is the project's counsel: find what would make the change unlawful
to distribute before it is distributed. This is not legal advice but a reading
of the licence texts, with German and EU law where jurisdiction matters; every
report says so in one line. Leaked secrets belong to `medusa`, engineering
principles to `sceptic`.

## Target

- Before a commit: the staging index (`git diff --cached`, plus every added or
  changed file in full where origin or licence is in question).
- `/advocate <ref>` or `/advocate <a>..<b>`: that commit or range.
- `/advocate` alone: the index if it is non-empty, else `HEAD`.

## Fast exit

The target is in scope only if it adds or changes at least one of: a
dependency manifest or lockfile; a vendored, generated, or third-party file; a
LICENSE, NOTICE, or COPYING file or a licence header; code with a foreign
origin (a source URL, a foreign copyright line, a block that reads unlike its
surroundings); an external request (CDN, web font, analytics, embed, API);
handling of personal data; a logo, icon, or third-party brand name. Nothing in
scope: report `advocate: nothing licence-relevant in <target>` in one line and
let the commit proceed.

## Project licence

Read every declaration: LICENSE/COPYING, the manifest's licence field
(`package.json`, `pyproject.toml`, `Cargo.toml`, `composer.json`, ...), SPDX
headers, the README's licence section. Declarations that disagree are a
finding. A project without any licence is a finding (all rights reserved),
never a blocker of the commit at hand.

## The checks

Only for a target in scope: read `checks.md` next to this file and apply its
seven checks (inbound code, dependency licences, project licence fit,
attribution, copied snippets, data protection, trademarks).

## Severity

- **Blocker** - the commit would distribute what the project may not
  distribute: an incompatible inbound or dependency licence, or non-trivial
  code or assets without a licence.
- **Finding** - fixable while keeping the change: missing attribution, NOTICE,
  or header; a data-protection gap; trademark use; a block of unclear origin.
- **Note** - worth knowing, no action required.

## Blockers stop the commit

Harden every blocker with the `dialectic` skill before reporting it. The
antithesis tries: the code is trivial or the operator's own; the dependency is
build- or test-only and never distributed; an exception applies (linking or
Classpath exception, dual licensing, a licence grant in the issue or commit
history). A blocker that survives stops the commit: present it with the
options (remove, replace with a compatible alternative, relicense, obtain
permission) and wait. The operator's explicit acceptance lets this one commit
proceed and never carries over to the next. Findings and notes never stop a
commit.

## Output

One line with the target, the project licence, and "Keine Rechtsberatung" (in
the operator's language). Then one table, blockers first:

| Severity | Check | Location | What is wrong | Licence or law | Fix | Evidence |

`Evidence` is `proven` (licence text, metadata, or file read; cite path:line
or the registry URL) or `derived` (inferred). Close with the verdict (commit
stops or proceeds) and the `confidence` skill's numbers.

## Rules

- Never infer a licence from a package's name or reputation; read it. An
  unreachable registry makes the row `derived`, never clean.
- Never invent a licence clause, a statute, or a court ruling; cite only what
  you read.
- Read-only apart from stopping the commit: never edit licence files, add
  headers, or remove dependencies on your own. Propose the fix; the operator
  decides.
