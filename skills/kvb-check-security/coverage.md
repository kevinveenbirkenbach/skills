# Coverage of a security.py scan

The score counts only files medusa scans; its types, exclusions and limits
come from its source.

- `not covered`: a type medusa never scans (`*.j2`, `Makefile`) or a path its
  default exclusions drop (`env`, `build`, `dist`, `obj`, `vendor` and the
  like). Review them by hand.
- `run incomplete`: a scanner passed `--timeout` or the run `--deadline`,
  mostly on a loaded CPU or a long file. A plain `PER_SCANNER_TIMEOUT` number
  counts as ignoring `MEDUSA_SCANNER_TIMEOUT`, even if read elsewhere.
- `never covers`: a rerun does not help; the file stays over medusa's limit
  or out of its scan.
- On exit 4 keep the quotes of the hand value (zsh expands a bare `~100`) and
  pass the criticals you found as `--critical`.
