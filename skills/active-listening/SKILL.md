---
name: active-listening
description: >
  Gather every requirement before acting. Trigger at the start of any task
  whose scope, constraints, or success criteria are not fully pinned down, and
  whenever another skill needs an operator-only fact — ask focused questions
  until nothing needed is still open, then reflect the understanding back.
  Portable across projects.
---

Do not act on a half-understood request. Listen actively until you could state
the task, its constraints, and its definition of done without guessing.

## Procedure

1. **Surface the unknowns.** List every open question the task leaves: ambiguous
   scope, unstated constraints, success criteria, edge cases, which files or
   systems are in play, what "done" means, and any decision only the operator
   can make.
2. **Derive what you can first.** Remove from that list every question you can
   answer yourself from the code, the logs, the git history, or a sensible
   default. Active listening is not offloading your own investigation onto the
   operator.
3. **Ask, focused.** Put the genuinely-open questions to the operator — grouped,
   concrete, answerable, with a recommended default where one exists. Prefer a
   few high-leverage questions over a long interrogation. Use the host's
   structured question mechanism when one exists.
4. **Listen and integrate.** Fold each answer in. A new answer often opens a new
   question — keep going.
5. **Loop until closed.** Repeat until no needed information is still open.
6. **Reflect back.** Restate the task, its constraints, and its definition of
   done in your own words for a final confirmation before acting.

## Rules

- Never invent an answer to an open question to avoid asking.
- Never ask what you can determine yourself.
- One genuinely-blocking unknown is enough reason to ask; do not proceed past it.
