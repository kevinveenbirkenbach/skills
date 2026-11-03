# Writing a skill

## Persistence

Only under `.claude/skills` a skill is lost on the next install; only in the
repository it is not live until the next restart. Write **both**, in order:

1. **Locate the skills repository**, first hit: the `SKILLS_REPO` variable;
   the current repository when it holds `skills-lock.json` and `skills/`;
   `pkgmgr path skills`; a git checkout named `skills` carrying
   `skills-lock.json` under `~/Repositories/*/*/skills`, `~/git`, `~/src` or
   `~/Projects`. None: ask for the path with a single-select question; never
   write only the live copies.
2. **Source of truth**, the committed copy: `skills/<name>/SKILL.md` in that
   repository (portable) or in the current project (project-specific).
3. **Mirror live**: copy the whole skill directory, so hooks and references
   come along, to `~/.claude/skills/<name>/` and `~/.agents/skills/<name>/`; a
   project-specific one also to the project's `.claude/skills/<name>/` and
   `.agents/skills/<name>/`.

Report every written path. Delete or rename in reverse, mirrors included, or
the old name keeps firing.

## Content

- Frontmatter: `name` and a `description` saying what the skill does **and**
  when it triggers; it is the only part loaded in every session, so it decides
  whether the skill fires.
- Body thin and single-purpose: the smallest instruction that changes
  behaviour; route to the authoritative doc instead of duplicating it.
- Optimizing makes a skill shorter or sharper, never longer: drop rules the
  agent already follows, merge duplicates, cut every sentence that changes no
  action. Route that compaction through the `kvb-skill-essence` skill (health
  pass for dead pointers and cross-skill duplicates first, ranked by what loads
  every session, diff before writing); answer its scope question with the
  skill being optimized.
- Report the change in at most three lines, then `date +%s >
  ~/.claude/.autotune-stamp` so the next hint is an hour out.
