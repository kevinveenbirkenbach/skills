---
name: kvb-code-tune
description: >
  Speed up CI, deploys, builds and hot paths without losing logic or
  coverage. Trigger on a job over its time budget or where time goes.
---

One rule outranks every optimization: **nothing that reduces logic, coverage or
correctness counts as a speed-up.**

## Session limits

First run in a session: before measuring, invoke the `kvb-think-listen` skill
with the questions of `listen.md` next to this file. Keep the answers for the
session, never ask again, work only inside them; a candidate outside them
becomes a proposal. Invoked by another skill (kvb-ci-triage, kvb-ci-observe)
or an autonomous run: no questions; examine the handed-over log with the
defaults (10 s floor per run, the `kvb-org-split` skill's 90/5 bar as merge
bar, 60 minutes per delegated agent), ask only when an operator-only fact
blocks.

## Forbidden, whatever it saves

- Dropping a test, a spec, a play, a drill or a verification pass.
- Raising a timeout or budget so a slow thing fits instead of getting faster.
- Swallowed failures, retry-until-pass, a soft skip, a narrowed assertion.
- Trading error semantics, credential masking, concurrency safety or a lint's
  intent for speed. A per-item failure stays loud and names its item.

Testing less to shrink the clock is reported as a coverage cut for the
operator to decide, never applied as a tuning.

## Measure first

- Never tune the unmeasured; read numbers from logs, not by eye (`logs.md`
  next to this file for profilers, build logs and gate tables).
- Stream every run to a log file and compare runs by their logs; never re-run
  for a lost number.
- **Rank by fixed cost x count**: one console boot, package-manager call or
  container exec times how often the run pays it: a 1 s boot paid 28 times
  beats a 60 s download paid once.
- **The baseline is the newest log of the current code**; an older one may
  carry a step since replaced, and a saving against it is fiction.
- **Ansible**: measure with the `kvb-check-ansible` skill first.

## Coordinate every cost cluster

Before investigating a cluster (one step, hot path or repeated call), run the
`kvb-org-organize` Peer protocol with every session on this machine, not only
the lineage. The first to claim `cluster/<slug>`, `--work` naming its log line
and number, works it (between machines, the earliest announcement); a claim
without a measurement does not count. Its `kvb-org-rasci` key result is
`<step> from <before> to under <after>`, met only by the re-measurement.
Someone earlier: post them your measurements and findings
(`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post --to <holder>
"<text>"`), take the next cluster, never build a second optimization. A claim
ends with its release or the operator's reassignment.

## Always check

On each measured hot path, whatever the operator picked, listed in the output
even when clean:

- **Language and framework**: the most efficient fit? Time in computation or
  inside the framework: read `language.md` next to this file.
- **Unnecessary recursion**: a hot path recursing or a tool calling itself:
  read `recursion.md` next to this file.

## The loop

1. Measure; name the single biggest cost with its log line and number.
2. Coordinate it; work it only when you identified it first.
3. Read `candidate.md` next to this file; form one candidate, harden it with
   the `kvb-think-dialectic` skill, delegate, merge or propose, re-measure.
4. Repeat until the next candidate is worth less than the run measuring it.

## Output

One table, biggest saving first:

| Candidate | Before | After | Source | Verdict |

Rejected candidates stay with the reason they fell; proposals carry what would
close their gap.
