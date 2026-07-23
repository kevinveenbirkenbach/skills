---
name: observe
description: >
  Watch a named target (a CI run, a pipeline, a build, a log) on a fixed
  cadence and apply the triage skill whenever new failures appear. Trigger on
  /observe <target> or when the operator asks to keep monitoring something and
  fix regressions as they surface. Portable across projects.
---

Keep a target under continuous watch and act only when it degrades. The loop is
the watcher; triage is the response. Do not re-investigate failures already
resolved this session, and do not idle-poll work the harness will notify you
about.

## Before you start: fix the target

The operator names one concrete target: a CI run id or url, a pipeline, a
branch's checks, a build, or a log file. Restate it in one line and record the
current failure set as the baseline (the failures already known or already
fixed this session). Everything the watch reports is diffed against that
baseline, so a stale baseline re-triages solved failures.

## The loop

Drive this with `/loop` in dynamic mode (no fixed interval unless the operator
gave one): after each observation, schedule the next wake-up yourself and pass
the same `/observe` prompt back so the next firing repeats the watch.

1. **Poll the target.** Pull its current state (job list, check conclusions, the
   log's tail). Enumerate the failures exactly as the `triage` skill's step 1
   does: failure, cancelled, timed-out; a downstream aggregate that fails only
   because an upstream did is not its own failure.
2. **Diff against the baseline.** A failure is *new* only if it is not in the
   baseline and was not already triaged this session. If nothing is new, log one
   short line ("still green" / "N known failures, no change") and reschedule.
3. **Triage each new failure.** Invoke the `triage` skill on the new set only —
   which applies `dialectic` per failing job to a ~99% root cause and a real
   fix. Never mask (no retry-until-pass, no disabled check, no soft-skip). Fold
   each newly fixed failure into the baseline so it is not re-triaged.
4. **Reschedule.** Pick the next delay from what you are waiting on: an active
   run that changes every few minutes gets a check matched to its cadence; a
   quiet or long-running target gets a long fallback (1200s+). Keep watching
   until the target reaches a terminal state (run completed, pipeline finished)
   AND every failure it produced has a verified fix, then stop the loop.

## Rules

- The loop is a fallback timer, not a busy-wait: if the harness will notify you
  when tracked work finishes (a background task, a spawned agent), wait for that
  notification instead of polling for it; reserve the timed wake-up for external
  state the harness cannot see (a remote CI run, a deploy queue).
- Executed evidence beats reasoning: read the actual failing log line and the
  artifact, not the job title — triage and dialectic carry this through.
- One baseline, updated in place: dedup every observation against all failures
  seen so far, or a flaky-then-fixed failure reappears every cycle and the watch
  never converges.
- Report only on change: a new failure and its triage verdict, or a terminal
  "target is green, watch closed". Silence between changes is correct.
- Never invent results for a run still in progress; report what the poll
  actually returned.
