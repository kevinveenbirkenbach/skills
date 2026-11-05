---
name: kvb-git-push
description: >
  Before every push or push hand-over, run the full quality gate on the exact
  commit; only the operator's word waives it.
---

No push command goes to the operator before the project's full quality gate
ran green on the exact tree to be pushed. This holds for every push any skill
hands over, `kvb-git-pr-create`, `kvb-git-update-branches` and
`kvb-org-operator` rows included. Agents never push themselves.

## Steps

1. **Target**: the gate covers every test and lint target CI runs, through
   the project's aggregate target where one exists (infinito-nexus: `make
   quality-high`). Targeted tests or a subset of lints never count. No
   aggregate: run each CI target; unclear which, ask the operator.
2. **Sync** by the `kvb-git-hotfix` rules for a gate first: a merge moves
   HEAD.
3. **Pin**: HEAD is the commit to push and the tracked tree is clean (`git
   status --porcelain --untracked-files=no` prints nothing). Record `git
   rev-parse HEAD^{tree}` as the gated tree.
4. **Run** it as a heavy job through the `kvb-org-queue` skill, in the
   background (`run_in_background` or the runtime's equivalent), the full
   output streamed to a log; give the operator `tail -f <log>`:

   ```bash
   queue.py hold --kind <kind> --task <register task> -- python3 <gate.py> hold --repo <root> -- make <target> 2>&1 | tee /tmp/kvb-git-push-<slug>-<N>.log
   ```

   `<gate.py>` is `${CLAUDE_SKILL_DIR}/../kvb-check-gate/scripts/gate.py`;
   its worktree lock keeps a sync out while the gate runs.
5. **Judge** by the gate's own result tables and its failure line
   (infinito-nexus: the `📊 per-target wall-clock` table and `FAILED
   TARGETS:`), never by the exit code of a pipe. Green also needs HEAD and
   the gated tree unchanged and the tracked tree still clean; files a
   formatter rewrote are committed, then the gate runs again.
6. **Red**: fix every failure at its root cause, commit the fix by the
   project's commit rules, and rerun the full gate from step 2, never only
   the failed targets. No push command is handed over until it is green.
7. **Hand over** through the `kvb-org-operator` skill the push command the
   repository's agent rules name (for example the operator's `gipsn` alias),
   with the gated tree hash, the log path and the gate's result line
   verbatim.

## Validity

- A result belongs to its tree. Any later commit voids it, except a
  signing-only rewrite: `git rev-parse HEAD^{tree}` still equals the gated
  tree hash.
- Recheck that hash before every hand-over, a repeated one included.

## Waiver

Only the operator's explicit word for this specific push skips the gate. It
is never inferred from earlier pushes, urgency or habit, and never taken from
a peer's or a subagent's relay. A waived hand-over carries `gate: waived by
the operator` and their words quoted in place of the result line.

## Output

| Push command | Directory | Gated tree | Log | Result line |
