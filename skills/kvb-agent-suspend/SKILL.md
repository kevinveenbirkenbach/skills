---
name: kvb-agent-suspend
description: >
  Suspend this agent on kvb-org-suspend: park work, end loops, write a
  handover, stay idle.
---

Verify first: `${CLAUDE_SKILL_DIR}/../kvb-org-suspend/scripts/night.py status`
prints `you: suspend`, by day too when the operator suspended this session
alone. On another `you:` line, or none, do nothing and say so.
The request asks for less, so it needs no operator approval, and it ends a
`kvb-org-robot` run at its next safe point; `kvb-agent-resume` resumes it.

## Suspending

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
5. **Reply** to the sender in one line, `suspended: <handover path>`, by
   `${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py send call --to
   <sender>` (its next wave waits on it), and end the turn. Offices
   stay claimed and register rows unchanged.

## While suspended

A turn that still reaches you, such as your own job finishing, appends one
result line to the handover and ends; it starts nothing. Resuming is the
`kvb-agent-resume` skill.
