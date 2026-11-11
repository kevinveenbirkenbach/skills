---
name: kvb-agent-resume
description: >
  Resume this agent from kvb-agent-drain or kvb-agent-suspend into its old
  roles; kvb-org-resume sends it to all.
---

Verify first with `${CLAUDE_SKILL_DIR}/../kvb-org-suspend/scripts/night.py
status`:

- **No `you:` line, or `you: resumed`**: `kvb-org-resume` ended the night or
  the operator lifted this session's part; resume.
- **`you: drain` or `you: suspend`**: only the operator, typing this command in
  this session, resumes it alone; a peer's request does not. Run `night.py
  resume --alone`: the others stay in the mode, and the night rules of `kvb-org-suspend`
  apply to this session too.

## Resuming

1. Read your handover, `handover_night_<session id>.md` in this project's
   memory directory.
2. Recreate every loop it lists with its exact prompt and interval or cron
   expression.
3. Read the log of every job it lists; a finished job's result goes to its
   task.
4. Check `council.py list`, `radio.py show` and the default branch instead of
   trusting old state: messages held overnight beyond 100 were dropped.
5. Continue with the next step of each task. Your offices are still yours.

Reply to a resume message through the radio, not a wake:
`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post --to <sender>
"resumed: <what resumes>"`.
