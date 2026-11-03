---
name: kvb-skill-auto
description: >
  Turn operator repetition into a skill. Trigger when the operator repeats an
  instruction, correction or prompt pattern a third time, or says they keep
  repeating themselves.
---

Its objective is the `kvb-skill-tune` skill's **Objective** section: a skill is
worth creating only when it cuts tokens or time and raises quality; judge
every candidate against its three axes and rules.

When the operator repeats the same kind of instruction, correction or prompt
pattern (about three times, wording may vary):

1. Finish the current task first; never interrupt work in progress.
2. Then propose in one short paragraph: the observed pattern, a skill name,
   the trigger phrasing and what the skill would do. Ask whether to create
   it.
3. On approval, persist it exactly as the `kvb-skill-tune` skill's
   **Persistence** section specifies: write `skills/<name>/SKILL.md` in the
   operator's skills repository (or the current project for project-specific
   behavior), then mirror the skill directory into `~/.claude/skills/` and
   `~/.agents/skills/`, plus the project's `.claude/skills/` and
   `.agents/skills/` when project-specific. Follow the local naming
   conventions; keep the skill thin and single-purpose, routing to an
   authoritative doc instead of duplicating it. Its deterministic steps
   become a script through the `kvb-skill-compile` skill, not prose.
4. No skill for one-off work, secrets, or repetition an existing skill
   already covers; when one almost fits, propose extending it instead.
