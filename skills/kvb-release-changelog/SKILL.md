---
name: kvb-release-changelog
description: >
  Write the `pkgmgr release` message; prints only. Trigger on "release
  message", "changelog entry", before cutting a release, or pkgmgr's
  markdown-lint rejection.
---

Read `reasons.md` next to this file when a rule does not fit or a lint
finding is unclear, and `special.md` for: no tag, a failed previous-tag
workflow, a test- or CI-only release, no `markdownlint-cli2`, a pasted pkgmgr
rejection.

## 0. Listen, then brainstorm

Run the `kvb-think-listen` skill for what only the operator knows (the tag,
the audience, the highlights, what to leave out), reusing `listen.yml` when
the `kvb-release` skill passed one; then the `kvb-think-brainstorm` skill on
how each change reads for its user, before step 1.

## 1. Find the range

```bash
git fetch --tags
git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*'
git log --no-merges --format='%h %s%n%b' <tag>..HEAD
```

- The base is the newest `vX.Y.Z` tag reachable from HEAD.
- Drop `Release version X.Y.Z` commits, and any revert together with the
  commit it reverts inside the range.
- A subject is a lead, not the change: read the diff (`git show --stat`, then
  the hunks) when it does not say what changed for the user.
- With `gh`, read every workflow of the previous tag's commit and of HEAD
  (`gh run list --commit <sha> --json workflowName,status,conclusion`), not
  one picked by `-L 1`. Only a finished failure counts; queued, running or
  missing runs are normal.

## 2. Sort into sections

`feat`: Added, or Changed when it alters existing behaviour. `fix`, `perf`:
Fixed. `!` or `BREAKING CHANGE:`: Breaking, plus one Upgrade notes line per
required action. `docs`, `style`, `refactor`, `test`, `ci`, `build`,
`chore`: omitted unless a user sees the effect. Dependency bumps: one
line, or omitted. Order: Breaking, Added, Changed, Fixed, Version
jumps, Upgrade notes, Contributors (always, with URLs: `sections.md`);
empty sections left out.

## 3. Format

1. Section labels are plain lines ending in `:`; no `#` headings, no
   bold-only lines.
2. No version heading, date or "Release X.Y.Z" line.
3. One bullet, one line: too long means shorter, never wrapped.
4. Line length: the repository's MD013 limit (default 80);
   aim for 78 or less.
5. Lists: no nesting, a blank line before and after (MD004, MD032), the
   marker of the existing CHANGELOG.md's first list item; `-` without a
   CHANGELOG.md, the configured one when the repo's MD004 pins a style.
6. No backticks or code blocks: *names*, *--flags* and *paths* in `*`
   italics; `*`, not `_`, for emphasis (MD049).
7. Bullets read `Area: effect`: the component the user knows (Backup,
   Restore, CLI, Tests), then what changed for them, not how the code
   changed. No commit SHAs, no em dashes (use `:` or `;`).
8. No trailing whitespace (MD009), double blank lines (MD012) or bare URLs;
   wrap URLs as `<https://...>` (MD034).

## 4. Lint it the way pkgmgr does

Follow `lint.md` next to this file; print nothing before 0 errors.

## 5. Output

1. The message in one fenced `text` block, nothing else inside it.
2. `Bump: patch | minor | major` and why (breaking: major, `feat`: minor,
   otherwise patch).
3. The lint result (`markdownlint-cli2: 0 errors` or the manual check run).
4. Only when a workflow on HEAD finished as a failure: its name and run, and
   the advice not to release before it is green.

Then stop. Never edit CHANGELOG.md or a version file, never run
`pkgmgr release`, never tag: the operator releases.
