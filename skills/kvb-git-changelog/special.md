# Changelog: special cases

- **No `vX.Y.Z` tag reachable from HEAD**: the range is the whole history;
  say so.
- **A workflow of the previous tag's commit finished as a failure**: that
  version was never published. Say so under *Upgrade notes* and carry its
  upgrade notes forward to this release.
- **Nothing user-visible remains** (a test- or CI-only release): keep those
  commits under Fixed with an area prefix (`Tests:`, `CI:`) so the entry is
  not empty.
- **No `markdownlint-cli2`**: check by hand what pkgmgr's fallback checks
  plus the length limit: no line over the limit, no trailing whitespace, no
  backtick, no double blank line. Name that manual check in the output.
- **The operator pastes pkgmgr's rejection** (`changelog entry:7:81 error
  MD013/line-length ...`): apply the same N - 4 mapping to the message they
  used, shorten only the lines it names, and lint again.
