# Working one cluster in its sidetree

Run inside the cluster's own worktree, so no cluster's edits land under
another cluster's work or under a running gate or deploy. The `kvb-ci-triage`
skill's Rules apply here too.

1. **Dialectic**: invoke the `kvb-think-dialectic` skill for the cluster:
   form a thesis about the root cause from evidence (the job log, its
   artifacts, the code at the run's commit, git history), attack it with
   independent skeptics, and iterate to a ~99% thesis.
2. **Shared vs hidden causes**: a cluster is a hypothesis, not a proof; if
   the dialectic shows it splitting into two causes, split it, and the new
   cluster gets a funnel of its own. When a job hides a second failure behind
   the first, keep going until the job is actually green, not just past the
   first error.
3. **Fix at the root**: apply the real fix for each proven root cause in the
   sidetree, with a test and a negative control as the `kvb-org-split` skill
   demands. Light runs (no Docker, about a minute: targeted pytest or
   unittest, ruff, single lint files) self-admit with
   `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/watch.py admit --kind
   test-nostack`; `make test`, gates, deploys and anything with Docker keep
   the chair's request, grant and release. The fix enters the main line only
   at the funnel's bar (at least 90 % fix confidence, under 5 % break risk)
   after its independent review; below the bar the cluster ends as a
   proposal for the operator, never as a merge. Never mask a failure: no
   retry-until-pass, no disabling the check, no soft-skip. If a failure is
   genuinely external (upstream outage, flaky infra), confirm that with
   evidence and surface it honestly instead of fixing around it. Report every
   fix, proposal and abandoned attempt to the peers asked in step 3 of the
   skill with `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/news.py post
   "<text>"` (`--to <name>` per peer), then remove the sidetree.
