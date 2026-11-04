---
name: kvb-check-gate
description: >
  Prove 90/5: every `make test*` target green on the exact HEAD. Trigger
  before declaring 90/5 or labelling a PR, or on "gate status".
---

The gate rule, stated here and nowhere else: nothing is declared 90/5 (fix
confidence ≥ 90 %, break risk ≤ 5 %, cost and time ≤ 100 % in
`kvb-check-score`; over 100 %, ask the operator before the commit, naming
the cause) before every `make test*` target of the project, each Makefile target named `test` or starting with
`test-`, ran green on the exact head with a clean tracked tree. Until then
the numbers are provisional and every target not green is a residual.

`${CLAUDE_SKILL_DIR}/scripts/gate.py` reads the targets from the Makefile and
its includes without running make, and keeps results per commit in
`kvb-gate.json` in the git common dir: linked worktrees share them, a new
commit starts from zero.

## Steps

1. **Sync**: `${CLAUDE_SKILL_DIR}/../kvb-git-hotfix/scripts/hotfix.py sync
   --repo <root> --task <your register task>`, then `hotfix.py pending
   --repo <root>`, by the `kvb-git-hotfix` skill. A merge moves HEAD, so the
   gate starts over from there.
2. **List**: `gate.py list --repo <root>`. A warning about an unresolved
   include or target expression means the list may be short: read that line
   and name the gap. A project without any target keeps the gate open; ask
   the operator.
3. **Status**: `gate.py status --repo <root>`. `gate: green` ends here; a
   `missing hotfix` reason means back to step 1.
4. **Admit**: every gate target is heavy and runs only inside
   `${CLAUDE_SKILL_DIR}/../kvb-org-queue/scripts/queue.py hold` (step 5),
   which grants by rule and releases on exit. Only a single test module
   self-admits (`${CLAUDE_SKILL_DIR}/../kvb-org-organize/scripts/watch.py
   admit --kind test-nostack`), and it never turns a gate target green. A
   hotfix gate adds `--hotfix <slug>` and takes the next free gate slot.
5. **Run** the missing and red targets, tracked tree clean, in the
   background; give the operator `tail -f` on the log:

   ```bash
   queue.py hold --kind <kind> --task <register task> -- gate.py run --repo <root> --target <t> [--target ...] --log-dir /tmp/<slug> [--fail-regex <re> ...]
   ```

   Pass one `--fail-regex` per failure line the project prints while exiting
   0; infinito-nexus needs `FAILED TARGETS: \S`. A non-zero exit, a
   `make: ***` line, a matching regex or modified tracked files make a
   target red; the last stops the run. Before each target `run` asks
   `hotfix.py void` for it and every later one. Exit 3 (`void: merge main
   for hotfix <slug>, then rerun`): back to step 1, then through the queue
   again. Exit 75: the worktree is
   busy, the message names the holder; wait, then rerun.
6. **Judge** every red target by its `status` line and the log around it:
   caused by the change, already red on the default branch, or the
   environment. Fix the cause and rerun; looking unrelated never makes it
   green.
7. **Status** once more; its last line is the verdict.

## Rules

- Only `gate.py run` on this head marks a target green. A peer's report, CI,
  an older commit or a dirty tree never does.
- Every heavy command in a worktree (deploys, `make test`, other gates) runs
  through `gate.py run` or `gate.py hold --repo <root> -- <command>` in the
  background (`run_in_background`), never under a tool timeout or
  `TaskStop`. Their lock keeps `hotfix.py sync` out
  only while a host process under it lives; a `docker compose exec` deploy
  runs on in its container unguarded.
- 90/5 is allowed only on `gate: green` for the exact head: in
  `kvb-check-score`, the `90/5` label and the `kvb-org-split` bar.
- Never edit `kvb-gate.json` by hand.

## Output

| Target | Status | Log | Line |

Then the `gate:` line verbatim.
