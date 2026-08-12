---
name: triage
description: >
  Triage a failing CI run, pipeline, or job set to a verified root cause and a
  real fix. Trigger when a build, test, or deploy pipeline has one or more failed
  jobs. Applies the dialectic skill to every failing job independently. Portable
  across projects.
---

Drive a red pipeline to green by root cause, not by guesswork. Treat every
failing job as its own investigation, and do not declare a fix until that job's
root cause is proven.

## Procedure

1. **Enumerate every failing job.** Pull the run's job list and isolate each job
   whose conclusion is failure, cancelled, or timed-out. A downstream aggregate
   job that fails only because an upstream job did is not a separate root cause —
   note it and move on.
2. **Cluster the failures by error message.** Group the failing jobs by their
   actual failing line, not by job name. Jobs whose messages differ in anything
   but the interpolated identifiers (host, app, port, path) belong in separate
   clusters.
3. **Download artifacts per cluster.** Use the `ci-artifacts` skill for the
   mechanics — it covers per-job logs while a run is still in progress, which
   bundle to pull, and the grep hygiene that keeps a false positive from
   becoming a root cause. For each cluster, fetch every artifact of
   one representative job: reports, rescue diagnostics, inventories, container
   logs. Pull a second member's artifacts only when the representative's
   evidence does not explain the whole cluster. The job log usually names an
   artifact path and nothing more; the assertion text, the server-side
   exception and the state dumps are inside the artifact. Do this even when the
   log looks conclusive, because a log that explains the symptom rarely
   explains the cause.
4. **Dialectic per cluster.** For EACH cluster, invoke the `dialectic` skill:
   form a thesis about the root cause from evidence (the job log, its artifacts,
   the code at the run's commit, git history), attack it with independent
   skeptics, and iterate to a ~99% thesis. The clusters are independent, so run
   their investigations in parallel where the tooling allows.
5. **Distinguish shared vs hidden causes.** A cluster is a hypothesis, not a
   proof: if the dialectic shows one cluster splitting into two causes, split it.
   When a job hides a second failure behind the first, keep going until the job
   is actually green, not just past the first error.
6. **Fix at the root.** Apply the real fix in the repository for each proven root
   cause. Never mask a failure — no retry-until-pass, no disabling the check, no
   soft-skip. If a failure is genuinely external (upstream outage, flaky infra),
   confirm that with evidence and surface it honestly instead of fixing around
   it.
7. **Follow the run.** While the run is still in progress, re-check it
   periodically and triage each newly failed job as it appears. The run is done
   only when it has finished and every failure has a verified fix.

## Rules

- Executed evidence beats reasoning: read the actual failing log line and the
  artifact, not the job title.
- A derived source is not evidence. A conversation summary, your own earlier
  message, a cluster table you built ten minutes ago, or a subagent's report
  proves nothing on its own. Only the job log, the artifact, the code at the
  run's commit, and command output you just ran count. Quote them literally; if
  you cannot quote it, you do not know it.
- Re-derive after a context compaction. A summary carried across a compaction
  boundary preserves your conclusions but not the evidence under them, and a
  cluster assignment that was wrong stays wrong while reading as settled fact.
  Before acting on any pre-compaction attribution, rebuild it from the job logs.
- Classify each failure: a real defect (fix it), a flake or infra hiccup (prove
  it is transient before dismissing), or already-fixed-by-a-later-commit (verify
  the fix is present in the run's commit before claiming it).
- Report a per-job verdict: root cause, the artifact path and line that prove
  it, and the fix. A verdict that cites only the job log has not finished step 3.
