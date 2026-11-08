---
name: kvb-org-resume
description: >
  Resume every agent after kvb-org-drain or kvb-org-suspend into its old roles.
---

Undoes the night of `kvb-org-drain` or `kvb-org-suspend`; the state lives in
`${CLAUDE_SKILL_DIR}/../kvb-org-suspend/scripts/night.py`.

1. After a suspend, hand the operator one step first through the
   `kvb-org-operator` skill: `/config` → "Messages from your other sessions" →
   `accept`. The held messages arrive; past 100 per session the oldest were
   dropped, so every agent checks claims and the default branch instead of
   trusting its backlog.
2. `night.py resume` ends the night and prints every other live session.
3. Message them in waves of three, first line: "Operator ran kvb-org-resume:
   run kvb-agent-resume; verify with night.py status."
4. A handover whose session is not live (`ls
   ~/.claude/projects/*/memory/handover_night_*.md`, session id in the name)
   belongs to a session a reboot ended: hand the operator its resume through
   `kvb-org-operator` (reopen it from the VS Code session list, or `claude
   --resume <session id>` in a terminal), then send it the same message.

Every task resumes under its row in the `kvb-org-rasci` register.

## Output

| Session | Live | Reply |
