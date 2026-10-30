---
name: triage
description: >
  Triage a failing CI run, pipeline, or job set to a verified root cause and a
  real fix. Trigger when a build, test, or deploy pipeline has one or more failed
  jobs. Applies the dialectic skill to every failing job independently, the
  coordinate skill to every failure cluster, and the funnel skill to every
  cluster, so each cluster is fixed in its own worktree, and hands one log per
  cluster to the tune skill. Portable across projects.
---

Drive a red pipeline to green by root cause, not by guesswork. Treat every
failing job as its own investigation, and do not declare a fix until that job's
root cause is proven.

## Procedure

0. **Check the run against HEAD before anything else.** A CI run is a snapshot
   of one commit, and the branch has moved since. Run
   `git log --oneline <run-sha>..HEAD | wc -l` as the first command of the
   triage. Zero means the run speaks for the current tree and you proceed.
   Non-zero means it does not, and you scope the job set down **before**
   enumerating, clustering, or spawning anything — every job you investigate
   against stale code is work thrown away, and a fix proposed there risks
   reverting someone else's. Two cheap discriminators do it without opening an
   artifact: `git diff --name-only <run-sha>..HEAD -- <source dir> | cut -d/ -f2 | sort -u`
   for which components already moved, and a grep of the saved job logs for the
   literal error signature of each cause already fixed in that range. What
   survives both is the job set the rest of this procedure applies to; say how
   many jobs you dropped and why.
1. **Enumerate every failing job.** Pull the run's job list and isolate each job
   whose conclusion is failure, cancelled, or timed-out. A downstream aggregate
   job that fails only because an upstream job did is not a separate root cause —
   note it and move on.
2. **Cluster the failures by error message.** Group the failing jobs by their
   actual failing line, not by job name. Jobs whose messages differ in anything
   but the interpolated identifiers (host, app, port, path) belong in separate
   clusters.
3. **Coordinate every cluster.** Invoke the `coordinate` skill for each cluster
   before fixing it: tell the agents whose branches this one inherits from or
   passes its commits on to which run failed and on which line, ask whether
   someone already fixes it, and either take their fix or claim yours through
   the `democracy` skill. Keep
   investigating while you wait for answers.
4. **Download artifacts per cluster.** Use the `ci-artifacts` skill for the
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
5. **One funnel per cluster.** Hand every cluster you claimed in step 3 to the
   `funnel` skill: one agent per cluster, working in its own worktree on its own
   branch created from the exact current HEAD, with that cluster as its only
   concern, the artifact paths of step 4 in its brief and a hard time cap.
   Steps 6 to 8 run inside that sidetree, so no cluster's edits land under
   another cluster's work or under a running gate or deploy. Run clusters in
   parallel only when their fixes touch different files and the machine has
   room. A split cluster (step 7) gets a funnel of its own.
6. **Dialectic per cluster.** For EACH cluster, invoke the `dialectic` skill:
   form a thesis about the root cause from evidence (the job log, its artifacts,
   the code at the run's commit, git history), attack it with independent
   skeptics, and iterate to a ~99% thesis.
7. **Distinguish shared vs hidden causes.** A cluster is a hypothesis, not a
   proof: if the dialectic shows one cluster splitting into two causes, split it.
   When a job hides a second failure behind the first, keep going until the job
   is actually green, not just past the first error.
8. **Fix at the root, through the funnel.** Apply the real fix for each proven
   root cause in the cluster's sidetree, with a test and a negative control as
   the `funnel` skill demands. The fix enters the main line only at the funnel's
   bar (at least 90 % fix confidence, under 5 % break risk) after its
   independent review; below the bar the cluster ends as a proposal for the
   operator, never as a merge. Never mask a failure: no retry-until-pass, no
   disabling the check, no soft-skip. If a failure is genuinely external
   (upstream outage, flaky infra), confirm that with evidence and surface it
   honestly instead of fixing around it. Report every fix, every proposal, and
   every abandoned attempt to the same agents through the `coordinate` skill,
   then remove the sidetree.
9. **Tune one log per cluster.** For each cluster, hand one job log to the
   `tune` skill: the cluster's job that ran furthest, because its timings cover
   the most phases. `tune` looks for performance potential in it under its own
   rules and the session's limits. Its candidates run through funnels of their
   own, separate from the cluster's fix sidetree, and never delay or block the
   fix. A log the failure cut short is tuned for the phases it covers; say which
   phases it does not reach.
10. **Follow the run.** While the run is still in progress, re-check it
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
  it is transient before dismissing), or already-fixed-by-a-later-commit. For
  that last class the comparison is `<run-sha>..HEAD`, never the run's commit
  alone: the run cannot contain a fix that landed after it, so looking there
  can only ever confirm the failure. Name the commit that carries the fix.
- Report a per-job verdict: root cause, the artifact path and line that prove
  it, the fix, the cluster's sidetree branch, and the funnel verdict (merged or
  proposal). A verdict that cites only the job log has not finished step 4.
