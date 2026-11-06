---
name: kvb-org-update
description: >
  Tell every agent which skills changed, as one newsletter. Run after
  installing skills.
---

Agents keep the skill text they read earlier in their context and go on using
it. `${CLAUDE_SKILL_DIR}/scripts/update.py` sends one newsletter through the
`kvb-org-radio` skill that names each changed skill with its latest commit
subjects and tells every agent to re-read that `SKILL.md` before its next use.

```bash
update.py --repo <skills repo> [--since <rev>] [--dry-run] [--session <id>]
```

## Steps

1. After `make install` of the skills repository, run `update.py --repo
   <skills repo> --dry-run` and check the text.
2. Run it without `--dry-run`. It sends the newsletter and records `HEAD` as
   announced in the council directory, so the next run starts there; a run
   without new skill commits sends nothing.
3. The first run on a host only records `HEAD`; pass `--since <rev>` to
   announce from an older revision, for example the last released tag.

## Rules

- One newsletter per update, never a radio class: agents read it when their
  turn ends, and the old commands stay valid as aliases until then.
- A change that breaks a running agent's command needs an alias in the
  changed script first; this skill only tells, it never migrates.
- Other runtimes read the newsletter with `radio.py show`.
- Add `update.py` as a tool of your task in the `kvb-org-rasci` register.
