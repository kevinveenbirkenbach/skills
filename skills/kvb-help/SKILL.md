---
name: kvb-help
description: >
  List and explain every session skill. Trigger on "welche skills gibt es",
  "skill übersicht", or questions on what skills exist or do.
---

Produce a one-shot overview of every skill the session can invoke:

1. Sources, in this order: the session's available-skills listing, the
   project's own skills (`skills/` and `.claude/skills/` in the repo), the
   user-global skills (`~/.claude/skills/`), and plugin-provided skills.
   Deduplicate by name; note when a project skill shadows a global one.
2. Output one table per origin (project, global, plugin): skill name,
   trigger (slash command or phrasing), one-line purpose in your own words,
   compressing the description instead of pasting it.
3. When the operator names a specific skill or topic, explain only the
   matching skills in more depth: what they do, when they fire on their
   own, and how they compose (e.g. kvb-git-commit-next →
   kvb-git-commit-no-verify → kvb-code-clean).
4. End with the activation hint: project installers or `make install` in
   the skills repository refresh the live copies; a restart loads renamed
   or new skills.
