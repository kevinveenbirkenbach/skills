# Lint it the way pkgmgr does

1. Write `# Changelog`, blank line, `## [X.Y.Z] - <date>`, blank line, the
   message to a scratch file outside the repository.
2. From the repository root, so its config applies:
   `markdownlint-cli2 --no-globs - < <scratch-file>`.
3. A finding on line N is message line N - 4: shorten it and lint again;
   print nothing before 0 errors.
4. Lint a scratch copy of CHANGELOG.md with the wrapped entry inserted below
   its `# Changelog` line the same way. A finding in older entries that the
   unmodified file lacks comes from the new entry: fix the message, never
   the older entries.
