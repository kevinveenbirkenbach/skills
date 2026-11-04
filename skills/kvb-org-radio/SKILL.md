---
name: kvb-org-radio
description: >
  Default channel for every message to other agents: board news, direct
  calls, security, pan-pan and mayday; wake a peer only when it must act.
---

`${CLAUDE_SKILL_DIR}/scripts/radio.py` is the channel every skill uses to
reach other agents, on every runtime. All classes share one store,
`news.jsonl` in the council directory (`/tmp/agents-council`); the old
`kvb-org-organize/scripts/news.py` forwards here.

```bash
radio.py send <class> "<text>" [--to <name> ...] [--wake] [--session <id>]
radio.py post "<text>" [--to <name> ...] [--session <id>]
radio.py show [--all] [--session <id>]
radio.py clear [--force] [--session <id>]
```

`post` is `send broadcast`, or `send direct` with `--to`.

## Classes

| Class | Addressee | Delivery | Wakes | Speed | Rough cost |
| --- | --- | --- | --- | --- | --- |
| broadcast | all | board line at each session's next prompt | no | next prompt | ~40 tokens per reader |
| direct | `--to` names | board line at the addressee's next prompt | only with `--wake` | next prompt; `--wake` within 15 s | ~40 tokens; a wake is a full turn of the receiver, very expensive |
| security | all | after the receiver's next tool batch, else next prompt | no | seconds while it works | ~40 tokens per reader |
| pan-pan | all | like security, listed above it | no | seconds while it works | ~40 tokens per reader |
| mayday | all | like pan-pan, plus a wake of every idle session and radio silence | yes | within 15 s | a full turn of every receiver, very expensive |

Pick the lowest class that does the job:

- **broadcast**: status that asks nothing (a result, a freed slot, a merge).
- **direct**: the same for one or a few peers.
- **security**: a hazard peers must know before their next step (main red,
  a moved path, a flaky host).
- **pan-pan**: urgent trouble that blocks others' work and needs help soon,
  but endangers no shared state.
- **mayday**: shared state in danger (disk full, a broken shared branch, a
  leaked credential); every agent stops starting heavy jobs.

## Rules

- Wake only with `mayday` or `direct --wake`, and only when the recipient
  must act or answer; this replaces `SendMessage`. For an addressee no
  listener wakes yet, `send` prints `wake: SendMessage to <name>`: send that
  peer the same text once with your runtime's message tool.
- Hotfixes are announced automatically when
  `${CLAUDE_SKILL_DIR}/../kvb-git-hotfix/scripts/hotfix.py` records them
  merged; never post them yourself.
- A mayday holds radio silence for two hours: every prompt shows `MAYDAY
  ACTIVE`, the resource watch blocks new heavy jobs, running ones go on. Its
  sender ends it with `radio.py clear` once resolved. Never clear another
  agent's mayday; `--force` only on the operator's order.
- One event, one row: no greeting, no acknowledgement, nothing the board
  or the `kvb-org-rasci` register already shows; read them before asking.
- No secret, token or credential value in a text: name where it lives.

## Delivery

On Claude Code three hooks deliver, each row once per session: `hook`
(UserPromptSubmit) prints the unseen rows, urgent first, at most 10; `tool`
(PostToolBatch) adds unseen urgent rows to a running turn; `listen` (Stop,
`asyncRewake`) wakes an idle session for a mayday or a `direct --wake`.
Subagents get nothing; their parent session reads the radio.

Other runtimes (Codex, Gemini CLI, Hermes, OpenClaw) use the same store and
scripts with `--session <id>` and read with `radio.py show` at session start
and before every heavy job; nothing wakes them.
