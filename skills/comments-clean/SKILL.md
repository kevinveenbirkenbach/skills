---
name: comments-clean
description: >
  Purge explanatory comments from staged and unstaged changes. Run
  AUTOMATICALLY, without being asked, every time the operator requests a
  commit or stage in any wording (commit, commit no-verify, stage next,
  socon, sobu, socobu, "commite ..."), BEFORE executing that request; also
  on /comments-clean or when the operator complains about comments.
  Explanatory comments are bad practice: they narrate code instead of
  letting it speak. Portable across projects.
---

When the operator asks to commit or stage, run this audit first and only
then perform the requested git action; never ask whether to run it.

Audit every staged and unstaged change (`git diff` plus `git diff --cached`,
added lines only) and delete every explanatory comment:

1. Delete: restated code, step narration, section banners, "Note that",
   rationale prose, apology comments, and any comment whose information the
   code, task name, or commit message already carries. When in doubt,
   delete.
2. Keep only: parameter/exit-code docs, nocheck/noqa/shellcheck directives,
   and project-sanctioned exception markers that name a concrete trip-wire.
   A relabeled narration is not an exception; delete it instead.
3. Block-comment languages are not line-oriented. In Jinja (`{# … #}`), C-like
   (`/* … */`), HTML (`<!-- … -->`) and their kin, a closing delimiter alone on
   its own line looks exactly like a comment line and gets deleted with the
   rest — after which the opening delimiter swallows every live statement down
   to the next closer. Never strip these languages with a line filter. Delete
   the whole block by hand, then count the delimiters (`grep -c '{#'` against
   `grep -c '#}'`) and re-parse the file.
4. Re-run the project's comment lint if one exists. A green lint does NOT prove
   the deletion was safe: a swallowed block is still syntactically valid, so
   both the lint and the language parser can pass over code that no longer
   executes. Diff against the pre-edit revision (`git show HEAD:<path>`) and
   confirm that only comment lines left.
5. Do not stage in order to run a check. Repository lints that enumerate through
   `git ls-files` already see every tracked file and read its worktree content;
   only an untracked NEW file is invisible to them and needs `git add`. Staging
   a tracked, modified file before a lint changes nothing except the operator's
   index, which they then have to undo. Stage only what a requested bundle
   contains, and re-stage after the audit exactly the files that were staged
   before it.
6. Penalty: if this audit finds anything you wrote yourself, admit it in
   the report (file and count, no excuses), lower your confidence numbers
   for the affected bundle, and write the incident to persistent agent
   memory (extend the existing minimal-comments feedback entry with the
   date and the pattern you slipped on) so the calibration survives the
   session.
