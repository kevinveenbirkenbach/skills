---
name: kvb-code-clean
description: >
  Purge comments, forbid defaults, check SPOT, DRY, SRP and coupling in a
  change. Run AUTOMATICALLY before every commit or stage request and while
  writing code.
---

On a commit or stage request run this pass first, unasked; Step 2 also
binds while writing code. Target: the added lines of `git diff` and `git
diff --cached`. Never stage to run a check; re-stage exactly what was
staged.

## Step 1: comments

Delete every added comment but an exception, a parameter doc or a nocheck
directive (`comments.md` next to this file). Rerun
`${CLAUDE_SKILL_DIR}/scripts/comments.py --repo <dir>` (`--staged`, `--file`
as in Step 2) until only kept hits remain; exit 1 means hits. Run the
repository's comment lint too.

## Step 2: defaults

Every parameter, setting and environment lookup comes from its caller; a
missing one aborts naming the key and where to set it. Run
`${CLAUDE_SKILL_DIR}/scripts/defaults.py --repo <dir>` (`--staged`: index
only; `--file <path>`: an untracked file); exit 1 means hits, judged by
`defaults.md`.

## Step 3: principles

Run `${CLAUDE_SKILL_DIR}/../kvb-check-principles/scripts/principles.py
--repo <dir> --ccn 10 --nloc 50 --params 5 --min-tokens 50` (`--staged`,
`--file` as above) and the other `kvb-check-principles` lenses. Fix in place
only what keeps behaviour inside the bundle; show the rest as its table
before the commit call (`reference.md`).

## Report and penalty

One line per step with file and count; penalty:
`${CLAUDE_SKILL_DIR}/../kvb-check-confidence/chain.md`.
