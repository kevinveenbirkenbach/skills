---
name: kvb-ci-observe
description: >
  Watch a CI run, pipeline, build or log on a cadence and triage new failures.
  Trigger on a request to keep monitoring and fix regressions.
---

Keep a target under watch and act only when it degrades: the loop watches,
triage responds. Never re-investigate a failure already resolved this
session, and never poll work the harness will notify you about.

## Before you start: fix the target

The operator names one concrete target: a CI run id or url, a pipeline, a
branch's checks, a build, or a log file. Restate it in one line and record
the current failure set (known or already fixed this session) as the
baseline. Every observation is diffed against it; a stale baseline
re-triages solved failures.

## The loop

Drive it with `/loop` in dynamic mode (no fixed interval unless the operator
gave one): after each observation, schedule the next wake-up and pass this
skill's prompt back unchanged.

1. **Poll the target**: its job list, check conclusions or log tail; for a
   GitHub Actions run, the `kvb-ci-artifacts` skill's `ci_failures.py <run>`.
   Enumerate failures as the `kvb-ci-triage` skill's step 1 does: failure,
   cancelled, timed-out; a downstream aggregate that fails only because an
   upstream did is not its own failure.
2. **Diff against the baseline.** A failure is new only if it is neither in
   the baseline nor triaged this session. Nothing new: log one short line
   ("still green" / "N known failures, no change") and reschedule.
3. **Triage each new failure** with the `kvb-ci-triage` skill on the new set
   only; it applies `kvb-think-dialectic` per failing job to a ~99% root
   cause and a real fix. Never mask (no retry-until-pass, disabled check or
   soft skip). A new failure and its verdict go to peers as news, never as a
   message: `${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/news.py post
   "<target>: <job> <failing line> -> <verdict>"`. Fold each newly fixed
   failure into the baseline.
4. **Reschedule** by what you wait on: an active run that changes every few
   minutes gets a check matched to its cadence, a quiet or long-running
   target a long fallback (1200s+). Stop once the target reaches a terminal
   state (run completed, pipeline finished) AND every failure it produced
   has a verified fix.

## Rules

- The loop is a fallback timer, not a busy-wait: for tracked work the
  harness reports (a background task, a spawned agent), wait for that
  notification; reserve the timed wake-up for state the harness cannot see
  (a remote CI run, a deploy queue).
- Executed evidence beats reasoning: read the failing log line and the
  artifact, not the job title.
- One baseline, updated in place: dedup every observation against all
  failures seen so far, or a flaky-then-fixed failure reappears every cycle
  and the watch never converges.
- Report only on change: a new failure and its triage verdict, or a terminal
  "target is green, watch closed". Silence between changes is correct.
- Never invent results for a run still in progress; report what the poll
  returned.
