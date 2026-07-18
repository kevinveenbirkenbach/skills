---
name: help-skills
description: >
  List and explain every skill available in the current session. Trigger on
  /help-skills, "welche skills gibt es", "skill übersicht", or when the
  operator asks what skills exist or what a skill does. Portable across
  projects.
---

Produce a one-shot overview of every skill the session can invoke:

1. Sources, in this order: the session's available-skills listing, the
   project's own skills (`skills/` and `.claude/skills/` in the repo), the
   user-global skills (`~/.claude/skills/`), and plugin-provided skills.
   Deduplicate by name; note when a project skill shadows a global one.
2. Output one table per origin (project, global, plugin): skill name,
   trigger (slash command or phrasing), one-line purpose in your own words
   — compress the description, do not paste it.
3. When the operator names a specific skill or topic, explain only the
   matching skills in more depth: what they do, when they fire on their
   own, and how they compose (e.g. commit-next → commit-no-verify →
   comments-clean).
4. End with the activation hint: project installers or `make install` in
   the skills repository refresh the live copies; a restart loads renamed
   or new skills.
