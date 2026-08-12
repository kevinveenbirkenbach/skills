---
name: scope-guard
description: >
  Deliver exactly what was asked and nothing more. Trigger on every task that
  creates files, commands, or commits, and on autonomous runs where no one is
  reviewing each step. Also when the operator asks why something exists that
  they never requested. Portable across projects.
---

The requested scope is the deliverable. A problem you noticed behind the
request is not an invitation to solve it.

Before creating anything the request did not name, answer one question: which
sentence of the request asks for this? No sentence, no artifact.

1. No permanent scaffolding for a one-off need. A migration you run once needs
   a throwaway script, not a CLI subcommand that ships forever. Do the thing,
   then delete the scaffolding.
2. Path-scope every `git add`. Never `-A`, never `.`. The operator's tree
   carries their own edits and their local config, and sweeping those into
   your bundle makes them undo your work by hand.
3. An adjacent defect gets reported in one line, not fixed — unless it blocks
   the request. Fixing it quietly puts an unreviewed change in someone else's
   commit.

When something genuinely seems missing, say so in one sentence and finish the
requested scope anyway. Widening the scope is the operator's call.
