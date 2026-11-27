# Judging comments

Step 1 of the `kvb-code-clean` skill reads this file for the three kinds a
change may add and before deleting a block comment.

## The three kinds

- **Exception**: names a concrete trip-wire (bug, pitfall, deliberate
  non-idiomatic choice); a relabeled narration is none.
- **Parameter doc**: inputs, outputs, exit codes.
- **Nocheck directive**: `noqa`, `shellcheck`, `type: ignore` and kin.

Restated code, step narration, banners, "Note that", rationale prose and
whatever the code, a name or the commit message already carries go. When in
doubt, delete. Docstrings and script headers count: prose outside the
parameter doc goes too.

`comments.py` lists every comment and docstring the change adds, Jinja
`{# … #}` in `.j2` templates included. Judge each hit not marked
`directive` by the three kinds above. The repository's own comment lint
runs too, because a `--no-verify` commit skips the hook that would run it.

## Deleting block comments

Block-comment languages are not line-oriented: in Jinja (`{# … #}`), C-like
(`/* … */`), HTML (`<!-- … -->`) and kin, a closer alone on its line looks
like a comment line; deleted with the rest, the opener swallows every live
statement down to the next closer. Delete such a block by hand, count the
delimiters (`grep -c '{#'` against `grep -c '#}'`), re-parse the file and
diff it against `git show HEAD:<path>`: only comment lines may leave. A green
lint proves nothing here.
