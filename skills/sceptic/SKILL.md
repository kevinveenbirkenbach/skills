---
name: sceptic
description: >
  Analyse a repository, a path, or a diff with a hostile eye for violated
  engineering principles — SPOT, DRY, KISS, SRP, and security at the trust
  boundaries. Trigger on /sceptic, "sei skeptisch", "kritische analyse",
  "review the architecture", or when the operator asks what is wrong with the
  code rather than whether it works. Portable across projects.
---

The stance is adversarial: the code is guilty until its structure proves
otherwise. This skill hunts violated principles, not bugs (`code-review`),
not bloat (`ponytail-audit`), not leaked secrets (`medusa`). Read-only —
report the findings, change nothing unless the operator asks afterwards.

## Scope

The operator names the target: a repository, a directory, a role, or a diff.
Without a target, take the whole repository and rank by blast radius. State
the scope in one line before reporting, and name explicitly what you did not
read — an audit that silently covered half the tree reads as clean.

## The lenses

Apply each independently; a finding belongs to exactly one:

1. **SPOT** — one truth, one place. A value, a version, a hostname, a
   schema, a list of names that exists twice is a divergence waiting to
   happen. Name both locations and the drift they will cause.
2. **DRY** — repeated *knowledge*, not repeated text. Two blocks that look
   alike but change for different reasons are correctly separate; merging
   them is the violation. Prove the shared reason to change, or drop the
   finding.
3. **SRP** — one reason to change per unit. Look for the module that both
   parses and persists, the function whose name contains "and", the role
   that configures and deploys and monitors. The test: name the two
   stakeholders who would each demand a change here.
4. **KISS** — mechanism the problem never asked for: an abstraction with one
   implementation, a config value that never varies, a cache with no
   measured pressure, a retry loop around a deterministic call.
5. **Security** — only at trust boundaries: unvalidated input crossing into
   a query, a shell, a template, or a path; authorization checked in the
   caller instead of the resource; a secret in a default, a log, or an
   image layer; a permission wider than the operation needs. Defensive
   findings only.
6. **Silent defaults** — a fallback that substitutes a guess for a value the
   caller failed to supply, turning a misconfiguration into wrong behaviour
   instead of a loud failure. See the `no-defaults` skill.

## Method

- **Evidence before verdict.** Every finding carries `file:line` you actually
  read. Grep for the sibling occurrences before calling something a
  duplicate — one hit is not a pattern.
- **Name the failure.** A finding must state what concretely goes wrong:
  which value drifts, which caller breaks, which input reaches which sink.
  A finding whose worst case is "feels wrong" gets deleted, not softened.
- **Attack your own finding.** For anything consequential or expensive to
  fix, run it through the `dialectic` skill before reporting it — the
  strongest counter-argument is usually "these two are not the same
  knowledge" or "this boundary is already checked upstream".
- **Respect intent.** A deliberate marker (`ponytail:`, a documented
  exception, a nocheck directive with a reason) is a known ceiling, not a
  finding. Report it only when the ceiling has since been exceeded.

## Output

One ranked table, worst blast radius first:

| Severity | Principle | Location | What is wrong | Smallest fix |

Then three closing lines at most: what the scope excluded, which findings
survived `dialectic` versus which are still derived-only, and the single
finding to fix first. No per-finding paragraphs — the operator asks when a
row needs unpacking.

## Rules

- Never report formatting, naming taste, or missing comments; a linter owns
  those and the operator did not ask.
- Distinguish proven (grepped, read, reproduced) from derived (reasoned
  statically) per finding, and close with the `confidence` skill's numbers
  for the audit as a whole.
- No silent caps: if you ranked and cut, say how many findings were dropped
  and by what rule.
- Skepticism ends at the report. Do not fix, stage, or refactor as part of
  this skill.
