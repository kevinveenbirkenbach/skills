---
name: kvb-check-principles
description: >
  Find violated principles (SPOT, DRY, KISS, SRP, coupling, trust
  boundaries) in a repository, path or diff. Trigger on "sei skeptisch", "kritische
  analyse", or "review the architecture".
---

The stance is adversarial: the code is guilty until its structure proves
otherwise. This skill hunts violated principles, not bugs (`code-review`),
bloat (`ponytail-audit`) or leaked secrets (`kvb-check-security`). Read-only:
report, change nothing unless the operator asks afterwards.

## Scope

The operator names the target: a repository, directory, role or diff.
Without one, take the whole repository and rank by blast radius. State the
scope in one line and name what you did not read; a silent half-audit reads
as clean.

## The lenses

Apply each independently; a finding belongs to exactly one:

1. **SPOT**: one truth, one place. A value, version, hostname, schema or list
   of names that exists twice will diverge. Name both locations and the
   drift.
2. **DRY**: repeated *knowledge*, not text. Look-alike blocks that change for
   different reasons are correctly separate; merging them is the violation.
   Prove the shared reason to change, or drop the finding.
3. **SRP**: one reason to change per unit: the module that parses and
   persists, the function named "x and y", the role that configures, deploys
   and monitors. Name the two stakeholders who would each demand a change.
4. **KISS/YAGNI**: mechanism nobody asked for: an abstraction with one
   implementation, a config value that never varies, a cache with no measured
   pressure, a retry loop around a deterministic call.
5. **Security**, only at trust boundaries: unvalidated input reaching a
   query, shell, template or path; authorization checked in the caller
   instead of the resource; a secret in a default, log or image layer; a
   permission wider than the operation needs. Defensive findings only.
6. **Fail fast**: a fallback guessing a value the caller failed to supply,
   or a swallowed error: wrong behaviour instead of a loud failure (step 2
   of the `kvb-code-clean` skill).
7. **Coupling**: a dependency against the layer direction, an import cycle,
   a reach into another unit's internals.

## Method

- **Graph first**: explore through the codebase-memory-mcp graph
  (`search_graph`, `trace_path`, `get_architecture`, `detect_changes`; the
  `kvb-agent-optimize` skill sets it up), grep and read after.
- **Evidence before verdict**: every finding carries a `file:line` you read.
  Grep the sibling occurrences before calling something a duplicate; one hit
  is not a pattern.
- **Name the failure**: which value drifts, which caller breaks, which input
  reaches which sink. A finding whose worst case is "feels wrong" is deleted,
  not softened.
- **Attack your own finding**: run anything consequential or expensive to fix
  through the `kvb-think-dialectic` skill before reporting it; the strongest
  counter is usually "not the same knowledge" or "already checked upstream".
  Skeptics scale with the stakes; each brief names the `file:line` and the
  claim and caps the answer at five lines.
- **Respect intent**: a deliberate marker (`ponytail:`, a documented
  exception, a nocheck directive with a reason) is a known ceiling, a finding
  only once exceeded.

## Output

One table, worst blast radius first:

| Severity | Principle | Location | What is wrong | Smallest fix |

Then at most three lines: what the scope excluded, which findings survived
`kvb-think-dialectic` and which are still derived-only, and the one to fix
first.

## Rules

- Never report formatting, naming taste or missing comments.
- Mark each finding proven (grepped, read, reproduced) or derived (reasoned
  statically), and close with the `kvb-check-score` block for the audit.
- No silent caps: say how many findings a cut dropped, by what rule.
- Skepticism ends at the report: no fix, stage or refactor in this skill.
