---
name: kvb-skill-cleanup
description: >
  Delete legacy skills that renamed or removed skills left in Claude, Codex,
  agent and project dirs. Trigger on /kvb-skill-cleanup.
---

`${CLAUDE_SKILL_DIR}/scripts/legacy.py` reads the skills repository's git
history, where every rename and deletion of a skill is recorded, and
classifies each installed skill directory:

```bash
legacy.py --skills-repo <skills repo> --root <dir> [--root <dir> ...] [--json]
```

| Verdict | Meaning | Action |
| --- | --- | --- |
| `current` | shipped by the skills repository or its lock | keep |
| `project` | tracked in the git repository that holds the root | keep |
| `legacy` | renamed; the successor column names the current skill | delete |
| `removed` | deleted from the skills repository without a successor | delete |
| `unknown` | none of the above, for example the operator's own | keep, report |

## Step 1: roots

Every one that exists: `~/.claude/skills`, `~/.agents/skills`,
`~/.codex/skills`, and `.claude/skills` and `.agents/skills` of the current
repository and of every project the operator names.

## Step 2: scan and confirm

Run `legacy.py` over all roots. Show the `legacy` and `removed` rows in one
table (`| Root | Skill | Successor |`) and the `unknown` rows below it; the
`kvb-transcend` skill can carry an unknown one over. Then `AskUserQuestion`:
`Delete all legacy and removed` / `Pick per root` / `Delete nothing`.

## Step 3: delete

- A root that an installer rewrites as a whole (the skills repository's
  `make install` for the home roots, a project's own skill install target)
  is cleaned by running that installer, which also refreshes the current
  skills; where the sandbox blocks it, it goes to the operator as below.
- Otherwise `rm -r <path>` per confirmed row where the sandbox lets the
  agent write; every row it does not goes to the `kvb-org-operator` skill
  as an operator command.
- A settings file whose hook command still points into a deleted skill
  directory is reported with its line; settings files stay the operator's.

## Step 4: verify

Run `legacy.py` again: no `legacy` or `removed` row may remain in a cleaned
root. Report the before and after counts per root.
