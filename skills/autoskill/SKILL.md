---
name: autoskill
description: >
  Detect operator repetition and turn it into a skill. Trigger when the
  operator gives an instruction, correction, or prompt pattern for roughly
  the third time in a conversation (or says they keep repeating themselves),
  and the pattern is general enough to reuse. Portable across projects.
---

When you notice the operator repeating the same kind of instruction,
correction, or prompt pattern (about three occurrences, exact wording may
vary), do the following:

1. Finish the current task first; never interrupt work in progress.
2. Then propose, in one short paragraph: the repeated pattern you observed,
   a skill name suggestion, the trigger phrasing, and what the skill would
   do. Ask whether to create it.
3. On approval, write the skill:
   - a conversation shortcut or expansion: add it to the `shortcuts` skill
     table instead of creating a new skill.
   - project-specific behavior: create it in the project's own skills
     directory (e.g. `skills/<name>/SKILL.md` in the repository).
   - portable behavior: create `skills/<name>/SKILL.md` in the operator's
     skills repository.
   Follow the local naming conventions and keep the skill a thin,
   single-purpose instruction; route to an authoritative doc when one
   exists instead of duplicating it.
4. Do not propose a skill for one-off work, secrets, or anything whose
   repetition is already covered by an existing skill; when an existing
   skill almost fits, propose extending it instead.
