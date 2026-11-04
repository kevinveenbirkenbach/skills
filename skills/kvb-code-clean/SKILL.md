---
name: kvb-code-clean
description: >
  Purge comments, forbid defaults, check SPOT, DRY, SRP and coupling in a
  change. Run AUTOMATICALLY before every commit or stage request and while
  writing code.
---

On a commit or stage request, run this pass first, then the requested git
action; never ask whether to run it. Step 2's rule also binds while writing
code.

The target is the added lines of every staged and unstaged change (`git
diff` plus `git diff --cached`) and the units they touch. Never stage to run
a check; after the pass, re-stage exactly the files staged before it. A pass that changes a bundle
the operator already saw shows its new diff stat and score block before the
commit call.

## Step 1: comments

Delete every comment the change adds except three kinds:

- **Exception**: names a concrete trip-wire (bug, pitfall, deliberate
  non-idiomatic choice); a relabeled narration is none.
- **Parameter doc**: inputs, outputs, exit codes.
- **Nocheck directive**: `noqa`, `shellcheck`, `type: ignore` and kin.

Restated code, step narration, banners, "Note that", rationale prose and
whatever the code, a name or the commit message already carries go. When in
doubt, delete. Docstrings and script headers count: prose outside the
parameter doc goes too, and a `#` or `//` grep misses it.

Block-comment languages are not line-oriented: in Jinja (`{# … #}`), C-like
(`/* … */`), HTML (`<!-- … -->`) and kin, a closer alone on its line looks
like a comment line; deleted with the rest, the opener swallows every live
statement down to the next closer. Delete such a block by hand, count the
delimiters (`grep -c '{#'` against `grep -c '#}'`), re-parse the file and
diff it against `git show HEAD:<path>`: only comment lines may leave. A green
lint proves nothing here.

## Step 2: defaults

Every parameter, setting and environment lookup comes from its caller; a
missing one aborts early with an error naming the key and where to set it.
Optionality is an explicit `None` branch at the call site.

`false`, `null`, `""` and an empty list or map are free. Any other default
carries a comment saying why the value is right for every caller that omits
it; "sensible", "standard" and "usual" justify nothing.

Run `${CLAUDE_SKILL_DIR}/scripts/defaults.py --repo <dir>` (`--staged`:
index only; `--file <path>`: an untracked file); exit 1 means hits. Judge
hits by `defaults.md` next to this file; it also lists what the script
misses.

## Step 3: principles

Run `${CLAUDE_SKILL_DIR}/../kvb-check-principles/scripts/principles.py
--repo <dir> --ccn 10 --nloc 50 --params 5 --min-tokens 50` (`--staged`,
`--file` as above; McCabe's, pylint's and jscpd's limits, 50 NLOC one
screen). Its hits on changed lines are leads under SRP, fail fast,
KISS/YAGNI and DRY; a `skip:` line leaves that tool's lens to you. Apply the
other `kvb-check-principles` lenses (SPOT, security, coupling, DRY of
knowledge) by its method. Judge what this change adds or worsens; an older
violation is one report line, not a fix.

- Fix in place a violation the change introduced when the fix stays inside
  the bundle and keeps behaviour, proven by the tests covering the touched
  units before and after (the safety net of the `kvb-code-refactor` skill).
- Everything else goes into the report as the `kvb-check-principles`
  table, shown before the commit call; the operator's word decides whether
  the bundle lands as it is.

## Report and penalty

One line per step: comments deleted, defaults rewritten or justified,
principle findings fixed and open, each with file and count. Whatever you
wrote yourself is admitted without excuses, lowers the bundle's 🎯 fix and
raises its 💥 break, and goes into persistent agent memory (date and
pattern).
