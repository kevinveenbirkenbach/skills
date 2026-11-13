# Coverage of a security.py scan

The score counts only files medusa really scans; its types, path exclusions
and limits come from medusa's own source.

- `not covered`: a type medusa never scans (`*.j2`, `Makefile`) or a path its
  default exclusions drop (any path holding `env`, `build`, `dist`, `obj`,
  `vendor` and the like). Review those files by hand.
- `run incomplete`: mostly a fully loaded CPU, which pushes scanners past
  medusa's per-file timeout so their findings vanish.
- `never covers`: a rerun does not help; the named file stays over medusa's
  limit or out of its scan.
- On exit 4 keep the quotes of the hand value (zsh expands a bare `~100`) and
  pass the criticals you found as `--critical`.
