# Changelog: why each rule holds

pkgmgr writes one text to the CHANGELOG.md entry, the annotated release tag,
`debian/changelog` and the RPM `%changelog`; every rule keeps one of them from
breaking or mangling it.

- **HEAD failure**: pkgmgr's CI gate runs after the tag, so a workflow that
  failed on HEAD means pkgmgr would tag a release that never goes stable.
- **Plain section labels**: pkgmgr creates the tag with `git tag -a -m`,
  whose default `strip` cleanup deletes every line starting with `#`. A
  bold-only line fails MD036.
- **No version heading**: pkgmgr adds `## [X.Y.Z] - YYYY-MM-DD` itself.
- **One line per bullet**: RPM turns every non-empty line into its own `-`
  entry and Debian indents each line, so a continuation line becomes a
  separate, broken entry.
- **78 characters**: lines stay within 80 after Debian's two-space indent
  and RPM's two-character `-` prefix.
- **The existing list marker**: MD004's default *consistent* style takes the
  marker of the first list in the file, and pkgmgr puts the new entry on top,
  so a marker that differs from the older entries turns every older list
  into a finding.
- **No backticks**: pkgmgr rewrites inline code to *italic* in all four
  targets, and a fenced block fails its fallback lint.
- **The wrapped lint**: pkgmgr wraps the message as `# Changelog`, blank
  line, `## [X.Y.Z] - date`, blank line, message, then runs
  `markdownlint-cli2` with the target repository's own config; hence the
  N - 4 line mapping.
- **`--no-globs`**: it keeps the config's own globs from linting the whole
  tree too.
- **The whole-file lint**: the standalone check cannot see rules that
  compare the entry with the rest of the file (MD004 *consistent*, MD024
  duplicate headings), but the repository's own markdown lint and pre-push
  gate do.
- **The manual check**: it covers what pkgmgr's fallback checks, plus the
  length limit.

A message that follows every rule:

```text
Fixed:

- Backup: rsync -a stored no xattrs, ACLs or hardlinks; now -aHAX
- Restore: *--empty* no longer aborts on a database with an extension

Upgrade notes:

- First backup re-copies every attribute-carrying volume once in full
```
