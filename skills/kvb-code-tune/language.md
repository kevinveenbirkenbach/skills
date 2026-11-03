# Tune: language and framework

For example a Python hot path replaced by Rust, or a heavy framework layer by
a lighter one or the standard library:

- **Only for measured CPU-bound work.** When the profile shows the time in
  computation inside the process (parsing, hashing, rendering, tight loops),
  a compiled language can win by an order of magnitude. When the time goes
  to process start-up, network round trips or waiting, batching in the
  current language wins first, and a rewrite changes nothing.
- **Framework overhead**: when the profile puts the time inside the
  framework (import and start-up, middleware, ORM query building,
  serialization), compare a lighter framework or the standard library on the
  same input. An ORM issuing one query per item is fixed by batching the
  query, not by swapping the framework.
- **Prefer the narrowest cut**: rewrite the hot function as an extension
  module (for Python and Rust: PyO3 and maturin) or a small binary behind the
  same interface, before rewriting a whole tool.
- **Count the total cost**: a toolchain in CI, builds per target
  architecture, shipping binaries to every host, the team's ability to
  maintain the code, and test parity with the old implementation.
- **Prove it on a prototype**: the same input, the same machine state, a
  before and an after number, and the old test suite passing against the new
  code.
- A language or framework change is applied only when the session's limits
  allow new languages, frameworks or toolchains; otherwise it is submitted as
  a proposal with the prototype's numbers.
