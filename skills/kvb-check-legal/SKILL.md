---
name: kvb-check-legal
description: >
  Check a commit's licences, attribution, copied snippets, GDPR and
  trademarks. Run AUTOMATICALLY before every requested commit;
  also on "rechtlich prüfen", "lizenz prüfen".
---

Find what would make the change unlawful to distribute before it ships: a
reading of the licence texts with German and EU law, not legal advice.
Secrets belong to `kvb-check-security`, principles to
`kvb-check-principles`. Read `checks.md` next to this file before step 2.

1. **Target**: the staging index before a commit; a given `<ref>` or
   `<a>..<b>`; else the index if non-empty, else `HEAD`.
2. **Fast exit**: nothing in scope: report `advocate: nothing
   licence-relevant in <target>` and proceed.
3. **Project licence**: read every declaration.
4. **The checks**: apply all seven; grade blocker, finding or note.
5. **Blockers stop the commit** once hardened by `kvb-think-dialectic`;
   wait for the operator. Findings and notes never stop it.
6. **Output**: the line, table and verdict of `checks.md`, then the
   `kvb-check-score` block; shared rules in
   `${CLAUDE_SKILL_DIR}/../kvb-check-confidence/chain.md`.

Read-only: propose fixes, never apply them.
