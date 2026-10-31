---
name: tune
description: >
  Find and apply performance optimizations (CI, deploy, build, gate, hot
  paths) without reducing logic, coverage or correctness. Trigger on /tune,
  when a job dies on its time budget, when a pipeline or deploy grows slower,
  or asked where time goes.
---

# Tune

One rule outranks every optimization: **nothing that reduces logic, coverage or
correctness counts as a speed-up.**

## Once per session: listen first

The first time this skill runs in a session, invoke the `active-listening`
skill before measuring anything, and ask three questions through the host's
structured question mechanism. Offer each as a checklist (multi-select) with
suggestions, and allow free text:

1. **What to examine.** Suggestions: CI wall-clock, deploy duration, gate and
   test runtime, image pulls and build caches, per-item loops and process
   spawns, idempotency (work repeated on a second run), network round trips,
   and resource use (CPU, memory, disk, I/O). Language, framework and
   recursion are checked on every run anyway (see Always check).
2. **Which performance boundaries to keep.** Suggestions: time budgets per job,
   deploy or gate; resource caps (memory, CPU, disk headroom); a minimum saving
   per change (default 10 s per run); the measurement source that counts as
   the verdict.
3. **Which limits apply to optimizations.** Suggestions: the scope that may be
   changed (files, roles, services); whether new dependencies, toolchains or
   languages may be introduced; whether infrastructure or CI configuration may
   change; the merge bar (default: the `funnel` skill's 90 % confidence and
   under 5 % break risk); a time cap per delegated agent (default 60 minutes).

Keep the answers for the rest of the session and do not ask again. Work only
inside them; a candidate outside them becomes a proposal.

When another skill (triage, observe) or an autonomous run invoked tune, skip
the questions: examine the handed-over log, apply the defaults above, and ask
only when an operator-only fact blocks.

## Forbidden, whatever it saves

- Dropping a test, a spec, a play, a drill or a verification pass.
- Raising a timeout or budget so a slow thing fits instead of getting faster.
- Swallowed failures, retry-until-pass, a soft skip, a narrowed assertion.
- Trading error semantics, credential masking, concurrency safety or a lint's
  intent for speed. A per-item failure stays loud and names its item.

A change that makes the clock smaller by testing less is reported to the
operator as a coverage cut for them to decide, never applied as a tuning.

## Measure first

Never tune what has not been measured, and read numbers from logs, not by eye.

- **Task profilers** (Ansible `profile_tasks` and similar) print the duration
  of the *previous* task under the *next* task's header. Pair each header with
  the following timestamp line, or read the end-of-run recap.
- **Build logs** (BuildKit): pair `#N [service x/y] RUN …` with `#N DONE Xs`
  by step number; `CACHED` marks a hit.
- **Gates**: per-target wall-clock tables and failed-target lines. An exit code
  piped through `tee` is not a verdict.
- **Code paths**: a profiler (py-spy, cProfile, perf, flame graphs) tells
  whether time goes to CPU, to I/O and waits, or to process start-up.
- Stream every run to a log file and compare runs by their logs; never re-run
  to recover a lost number.
- **Rank by fixed cost x count.** Measure the per-call fixed cost (one
  application console boot, one package-manager call, one container exec) and
  multiply by how often the run pays it. A one-second boot paid twenty-eight
  times is a candidate; a sixty-second download paid once is not.
- **The baseline is the newest log of the current code.** An older log may
  still carry the step a previous optimization replaced, and a saving measured
  against it is fiction.

## Invalid comparisons

Discard a before/after pair, not just its noise, when:

- Another gate, deploy or heavy job shared the machine during either run.
- The two runs differ in image or cache state. A cold build after a cache prune
  or a Dockerfile edit is expected: before calling a cold build a defect,
  compare the instruction text and the base image digest across both logs.
- One run pays a one-time cost (first install, migration, purge, model
  download) the other does not.
- A long wait hides retries or a failure; count retry lines before calling it
  slow.
- A fresh-install pass is compared with an update pass. Analyse each pass of a
  multi-pass run separately.

## Before you optimize

- **Search every branch** (the merge-fix skill's `find_fix.py -S <symbol> --path <path>`) for a change
  that already removes or reshapes the step. A fix on a sibling branch can make
  the whole candidate worth zero.
- A step that is long by design (a backup and restore drill, an end-to-end
  suite) is not a candidate. Its cost buys its guarantee.
- Apply the session's saving floor: a smaller saving is listed as "below
  floor" and dropped.
- Pruning build caches to free disk costs a cold rebuild of every custom image
  on the next run. Name that cost before anyone prunes.

## Coordinate every cost cluster

A cost cluster is one place the time goes: one step, one hot path, one
repeated call, named by its log line and its number. Before investigating or
implementing a cluster, run the `democracy` skill's Peer protocol for it with
every agent session on this machine, not only the branch lineage.

- **The first to identify a cluster works it.** "First" is the `democracy`
  claim `cluster/<slug>`, whose `--work` names the cluster's log line and
  number; between machines, the earliest announcement by message time. A
  claim without a measurement does not count.
- **Someone was earlier:** send them your measurements and findings, then move
  on to the next cluster. Never build a second optimization of the same
  cluster.
- **A claim ends** when its holder reports the result, a proposal or an
  abandoned attempt and releases it, or when the operator reassigns it.

## Always check

Every run examines these two on each measured hot path, whatever the operator
picked in the first question, and lists the result in the output table, a
clean result included:

- **Language and framework**: whether the hot path's language and framework
  are the most efficient fit for its work (see Language and framework).
- **Unnecessary recursion**: a recursive function that recomputes the same
  subproblem (memoize it or turn it into a loop), recursion that only walks a
  list or a fixed depth (a loop), a tree walk that visits or reads the same
  node more than once, depth that grows with the input (stack limits, Python's
  1000 frames), and recursive tool calls: a make target calling make, a role
  or playbook including itself, a script re-invoking itself per item. Count
  the calls first (a profiler's call graph, cProfile's `ncalls`, log lines);
  recursion that is bounded, rare and cheap stays.

## Levers that usually pay

- **Batch per-item process spawns**: N calls that each boot an interpreter or
  an application console become one process running N commands (one app
  console boot, one module, one batched API request). Keep each item's failure
  named and the exit code honest.
- **Skip no-op work** a previous step already did, such as a separate enable
  after an install that already enabled.
- **Idempotency flip-flops**: any `changed` on a second consecutive run.
- **Image pulls and builds**: pull only what the host lacks; keep build caches
  warm.
- **Overlap waits with work** only where concurrent execution is proven safe.
  Schema migrations and lock-holding steps are usually not.

## Language and framework

Check the language and the framework of every measured hot path, for example
replacing a Python hot path with Rust, or a heavy framework layer with a
lighter one or the standard library:

- **Only for measured CPU-bound work.** When the profile shows the time in
  computation inside the process (parsing, hashing, rendering, tight loops),
  a compiled language can win by an order of magnitude. When the time goes to
  process start-up, network round trips or waiting, batching in the current
  language wins first, and a rewrite changes nothing.
- **Framework overhead**: when the profile puts the time inside the framework
  (import and start-up, middleware, ORM query building, serialization),
  compare a lighter framework or the standard library on the same input. An
  ORM issuing one query per item is fixed by batching the query, not by
  swapping the framework.
- **Prefer the narrowest cut**: rewrite the hot function as an extension
  module (for Python and Rust: PyO3 and maturin) or a small binary behind the
  same interface, before rewriting a whole tool.
- **Count the total cost**: a toolchain in CI, builds per target architecture,
  shipping binaries to every host, the team's ability to maintain the code,
  and test parity with the old implementation.
- **Prove it on a prototype**: the same input, the same machine state, a before
  and an after number, and the old test suite passing against the new code.
- A language or framework change is applied only when the session's limits
  allow new languages, frameworks or toolchains; otherwise it is submitted as
  a proposal with the prototype's numbers.

## Delegating an optimization

Hand every optimization to an agent through the `funnel` skill: one sidetree
per candidate, branched from an exact commit, with a time cap and "measure
first, report the time split before implementing". The agent probes live
systems read-only and never starts gates or deploys. A broad brief without a
cap can run for hours without a word; at its cap, collect the agent's interim
findings and let it run on.

Before merging, run independent skeptics through the `dialectic` skill. The
antithesis must try to show that the candidate removes coverage, hides a
failure, or only moves the cost somewhere the measurement does not look.

## The loop

1. Measure, and name the single biggest cost with its log line and number.
2. Coordinate the cluster with the other agents; work it only when you
   identified it first, otherwise hand over your findings and take the next.
   Then form one candidate for it, after the branch search and the floor check.
3. Harden it with the `dialectic` skill.
4. Funnel it through a sidetree; merge what reaches the bar, submit the rest as
   proposals. Re-measure from the same source under the same conditions and
   report a before and an after number.
5. Repeat until the next candidate is worth less than the run that measures it.

## Output

One table, biggest saving first:

| Candidate | Before | After | Source | Verdict |

Rejected candidates stay in the table with the reason they fell: below floor,
coverage cut, outside the session's limits, invalid comparison, made moot by
another branch, or cap reached without a measured result. Proposals carry what
would close their gap.
