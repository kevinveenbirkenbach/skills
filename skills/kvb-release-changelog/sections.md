# Version jumps, Contributors and net counting

## Net, not per commit

After a long-lived branch merges, `git log <tag>..HEAD` lists commits that
were already released under other SHAs (v16.2.3..main held 2430 commits; the
Wazuh role shipped in 16.1.0 and reappeared through the store-i18n merge).
Judge every Added, Changed and Fixed line against `git diff <tag>..HEAD` and
the earlier CHANGELOG.md entries, never against the commit list alone.

## Version jumps (net since X.Y.Z)

Only in a repository that pins a version per role
(`roles/*/meta/services.yml`): one `- *role*: old to new` line per role whose
pinned version differs between the tag and HEAD:

```bash
git diff <tag>..HEAD -- 'roles/*/meta/services.yml'
```

Compare the `version` field of every entity in each file at both refs: a
version bumped twice shows once, one changed and changed back not at all.
The same comparison covers every other pin:

- `ref` and `*_version` keys beside `version` (a pkgmgr `ref`, a
  `webui_version`, a `builder_version`).
- Add-on pins in `roles/*/meta/addons/*.yml`.
- Renamed or split roles: pair the old and the new role (`git diff -M
  --name-status <tag>..HEAD -- roles/`) before comparing, else the jump
  hides behind the rename. A rename without an alias is also a Breaking
  line plus an Upgrade note.
- Manifests outside the roles: `requirements/requirements.galaxy.yml`
  collections and the `pyproject.toml` pins.

A change that is no version bump (an image swapped for a source build, a
base like `cpu` becoming `22.04`, `2026.8.0` becoming `3.13`) needs
judgement: a Changed line or an Upgrade note, never a jump line.

## Contributors

Always, one `- [Name](URL): areas` line per human author and
`Co-authored-by` trailer in the range, the areas taken from that person's
commits:

```bash
git log --format='%aN%n%(trailers:key=Co-authored-by,valueonly)' <tag>..HEAD
git check-mailmap '<Name> <email>'
```

- Names go through `.mailmap`, so one person shows once.
- Bots stay out: dependabot, updaters, github-actions, Claude and other AI
  co-authors.
- The URL comes from earlier entries (CHANGELOG.md,
  `packaging/debian/changelog`); `.mailmap` holds none. A person without one
  there is asked for, never left without a URL.

Example:

```text
Contributors:

- [Kevin Veen-Birkenbach](https://veen.world): PHP hardening, Node.js
```
