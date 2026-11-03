---
name: kvb-agent-sleep
description: >
  Put this agent to sleep on kvb-org-sunset: park work, end loops, write a
  morning handover, stay idle. Trigger on its request.
---

Verify first: `${CLAUDE_SKILL_DIR}/../kvb-org-sunset/scripts/night.py status`
prints `you: sleep`. On `you: active` or `mode: day` do nothing and say so.
The request asks for less, so it needs no operator approval, and it ends a
`kvb-org-robot` run at its next safe point; `kvb-agent-wakeup` resumes it.

## Going to sleep

1. **Park** the current task at its next safe point. A running job (deploy,
   gate, test, build) runs to its end and is never cut short; note its log.
2. **Start nothing**: no task, job, subagent (`Agent`, `Workflow`) or peer
   message beyond the reply below.
3. **End your loops** (in Claude Code: `CronList`, then `CronDelete` for each
   job; `ScheduleWakeup` with `stop: true` for a self-paced loop; `TaskStop`
   for each `Monitor`).
4. **Handover**: write `handover_night_<session id>.md` (the id in
   `CLAUDE_CODE_SESSION_ID`) into this project's memory directory, replacing
   the last one and without a `MEMORY.md` line; at most 10 lines:
   - name and roles: offices from `council.py list --mine`, the chair, lines;
   - each loop with its exact prompt and interval or cron expression;
   - each running job with its command and log path;
   - each open task of yours in the `kvb-org-rasci` register with its next step.
5. **Reply** to the sender in one line, `asleep: <handover path>`, by
   `SendMessage` (its next wave waits on it), and end the turn. Offices stay
   claimed and register rows unchanged.

## While asleep

A turn that still reaches you, such as your own job finishing, appends one
result line to the handover and ends; it starts nothing. Waking up is the
`kvb-agent-wakeup` skill.
