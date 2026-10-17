---
name: changelog
description: >
  Write the release message for everything since the last release, ready to
  paste into `pkgmgr release` (its editor or `--message`). Trigger on
  /changelog, "release message", "changelog entry", or when the operator is
  about to cut a release or pastes pkgmgr's markdown-lint rejection of an
  entry. Prints the message only: never edits CHANGELOG.md, never tags, never
  releases. Portable across projects.
---

The message is one text that pkgmgr writes to four places: the CHANGELOG.md
entry, the annotated release tag, `debian/changelog` and the RPM `%changelog`.
Every rule below exists because one of those four would otherwise break or
mangle it.

## 1. Find the range

```bash
git fetch --tags
git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*'
git log --no-merges --format='%h %s%n%b' <tag>..HEAD
```

- pkgmgr tags every release `vX.Y.Z`; the newest one reachable from HEAD is
  the base. No such tag: the range is the whole history, say so.
- Drop the `Release version X.Y.Z` commits and any revert together with the
  commit it reverts inside the range.
- A subject is a lead, not the change: read the diff (`git show --stat`, then
  the hunks) when the subject does not say what changed for the user.
- When `gh` is available, check the previous tag's CI run
  (`gh run list --branch <tag> -L 1`). A failed run means that version was
  never published: say so under *Upgrade notes* and carry its upgrade notes
  forward to this release.

## 2. Sort into sections

| Commit | Section |
| --- | --- |
| `feat` | Added, or Changed when it alters existing behaviour |
| `fix`, `perf` | Fixed |
| `!` or `BREAKING CHANGE:` | Breaking, plus one Upgrade notes line per required action |
| `docs`, `style`, `refactor`, `test`, `ci`, `build`, `chore` | omitted unless a user sees the effect |
| dependency bumps | one collapsed line, or omitted |

When nothing user-visible remains (a test- or CI-only release), keep those
commits under Fixed with an area prefix (`Tests:`, `CI:`) so the entry is not
empty.

Order: Breaking, Added, Changed, Fixed, Upgrade notes. Leave out empty
sections.

## 3. Format

```text
Fixed:

- Backup: rsync -a stored no xattrs, ACLs or hardlinks; now -aHAX
- Restore: *--empty* no longer aborts on a database with an extension

Upgrade notes:

- First backup re-copies every attribute-carrying volume once in full
```

1. **Section labels are plain lines ending in `:`**, never `#` headings and
   never a bold-only line. pkgmgr creates the tag with `git tag -a -m`, whose
   default `strip` cleanup deletes every line starting with `#`. A bold-only
   line fails MD036.
2. **No version heading, date or "Release X.Y.Z" line.** pkgmgr adds
   `## [X.Y.Z] - YYYY-MM-DD` itself.
3. **One bullet, one line. Too long means shorter, never wrapped.** RPM turns
   every non-empty line into its own `-` entry and Debian indents each line,
   so a continuation line becomes a separate, broken entry.
4. **Line length: the repository's MD013 limit**, which is markdownlint's
   default of 80 unless the repo's config changes it. Aim for 78 or less, so
   lines stay within 80 after Debian's two-space indent and RPM's two-character
   `-` prefix.
5. **Lists use `-` only**, no nesting, with a blank line before and after
   every list (MD004, MD032).
6. **No backticks and no code blocks.** pkgmgr rewrites inline code to
   *italic* in all four targets, and a fenced block fails its fallback lint.
   Write *names*, *--flags* and *paths* in `*` italics yourself; use `*`, not
   `_`, for emphasis (MD049).
7. **Bullet text is `Area: effect`**: the component the user knows (Backup,
   Restore, CLI, Tests), then what changed for them, not how the code
   changed. No commit SHAs, no em dashes: use `:` or `;`.
8. **Plain hygiene**: no trailing whitespace (MD009), no double blank lines
   (MD012), no bare URLs: wrap them as `<https://...>` (MD034).

## 4. Lint it the way pkgmgr does

pkgmgr wraps the message as `# Changelog`, blank line, `## [X.Y.Z] - date`,
blank line, message, then runs `markdownlint-cli2` with the target repo's own
config. Reproduce that exactly:

1. Write that wrapped document to a scratch file outside the repository.
2. From the repository root, so its config is picked up, run:

   ```bash
   markdownlint-cli2 - < <scratch-file>
   ```

3. A finding on line N points at message line N - 4. Shorten that line and
   lint again; print nothing until the result is 0 errors.

Without `markdownlint-cli2`, check by hand what pkgmgr's fallback checks plus
the length limit: no line over the limit, no trailing whitespace, no
backtick, no double blank line.

When the operator pastes pkgmgr's rejection (`changelog entry:7:81 error
MD013/line-length ...`), apply the same N - 4 mapping to the message they
used, shorten only the lines it names, and lint again.

## 5. Output

1. The message in one fenced `text` block, nothing else inside it.
2. One line: `Bump: patch | minor | major` and why (breaking → major,
   `feat` → minor, otherwise patch).
3. One line with the lint result (`markdownlint-cli2: 0 errors` or the manual
   check that ran).

Then stop. Never edit CHANGELOG.md or a version file, never run
`pkgmgr release`, never tag: the operator releases.
