---
name: kvb-code-no-comments
description: >
  Purge explanatory comments from staged and unstaged changes. Run
  AUTOMATICALLY before every commit or stage request (commit, commit
  no-verify, stage next, "commite ..."); also on comment complaints.
---

On a commit or stage request, run this audit first, then the requested git
action; never ask whether to run it.

Audit the added lines of every staged and unstaged change (`git diff` plus
`git diff --cached`) and delete every explanatory comment:

1. Delete restated code, step narration, section banners, "Note that",
   rationale prose, apology comments, and any comment whose information the
   code, task name or commit message already carries. When in doubt, delete.
2. Keep only parameter and exit-code docs, nocheck/noqa/shellcheck
   directives, and project-sanctioned exception markers naming a concrete
   trip-wire. A relabeled narration is not an exception; delete it.
3. Block-comment languages are not line-oriented. In Jinja (`{# … #}`),
   C-like (`/* … */`), HTML (`<!-- … -->`) and their kin, a closing delimiter
   alone on its line looks like a comment line; deleted with the rest, it
   lets the opening delimiter swallow every live statement down to the next
   closer. Never strip these with a line filter: delete the whole block by
   hand, count the delimiters (`grep -c '{#'` against `grep -c '#}'`) and
   re-parse the file.
4. Re-run the project's comment lint if one exists. Green does NOT prove the
   deletion safe: a swallowed block stays syntactically valid, so lint and
   parser pass over code that no longer executes. Diff against the pre-edit
   revision (`git show HEAD:<path>`) and confirm only comment lines left.
5. Do not stage to run a check (the `kvb-git-commit-next` skill's step 4 says
   why). After the audit, re-stage exactly the files staged before it.
6. Penalty: anything you wrote yourself goes into the report (file and
   count, no excuses), lowers your confidence numbers for the affected
   bundle, and is written to persistent agent memory (extend the existing
   minimal-comments feedback entry with the date and the pattern you slipped
   on) so the calibration survives the session.
