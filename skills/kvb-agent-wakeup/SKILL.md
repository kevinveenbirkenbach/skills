---
name: kvb-agent-wakeup
description: >
  Wake this agent from kvb-agent-relax or kvb-agent-sleep into its old roles;
  kvb-org-sunrise sends it to all. Trigger on its request.
---

Verify first with `${CLAUDE_SKILL_DIR}/../kvb-org-sunset/scripts/night.py
status`:

- **`mode: day`**: `kvb-org-sunrise` ended the night; wake up.
- **`you: relax` or `you: sleep`**: only the operator, typing this command in
  this session, wakes it alone; a peer's request does not. Run `night.py
  wake`: the others keep sleeping, and the night rules of `kvb-org-sunset`
  apply to this session too.

## Waking up

1. Read your handover, `handover_night_<session id>.md` in this project's
   memory directory.
2. Recreate every loop it lists with its exact prompt and interval or cron
   expression.
3. Read the log of every job it lists; a finished job's result goes to its
   task.
4. Check `council.py list`, `radio.py show` and the default branch instead of
   trusting old state: messages held overnight beyond 100 were dropped.
5. Continue with the next step of each task. Your offices are still yours.

Reply to a sunrise message through the radio, not a wake:
`${CLAUDE_SKILL_DIR}/../kvb-org-radio/scripts/radio.py post --to <sender>
"awake: <what resumes>"`.
