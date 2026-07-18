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
3. Re-run the project's comment lint if one exists and re-stage the files
   that were already staged.
4. Penalty: if this audit finds anything you wrote yourself, admit it in
   the report (file and count, no excuses), lower your confidence numbers
   for the affected bundle, and write the incident to persistent agent
   memory (extend the existing minimal-comments feedback entry with the
   date and the pattern you slipped on) so the calibration survives the
   session.
