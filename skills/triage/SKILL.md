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
2. **Dialectic per failing job.** For EACH failing job, invoke the `dialectic`
   skill: form a thesis about the root cause from evidence (the job log, its
   artifacts, the code at the run's commit, git history), attack it with
   independent skeptics, and iterate to a ~99% thesis. The jobs are independent,
   so run their investigations in parallel where the tooling allows.
3. **Distinguish shared vs hidden causes.** When several jobs share one root
   cause, fix it once. When a job hides a second failure behind the first, keep
   going until the job is actually green, not just past the first error.
4. **Fix at the root.** Apply the real fix in the repository for each proven root
   cause. Never mask a failure — no retry-until-pass, no disabling the check, no
   soft-skip. If a failure is genuinely external (upstream outage, flaky infra),
   confirm that with evidence and surface it honestly instead of fixing around
   it.
5. **Follow the run.** While the run is still in progress, re-check it
   periodically and triage each newly failed job as it appears. The run is done
   only when it has finished and every failure has a verified fix.

## Rules

- Executed evidence beats reasoning: read the actual failing log line and the
  artifact, not the job title.
- Classify each failure: a real defect (fix it), a flake or infra hiccup (prove
  it is transient before dismissing), or already-fixed-by-a-later-commit (verify
  the fix is present in the run's commit before claiming it).
- Report a per-job verdict: root cause, the evidence that proves it, and the fix.
