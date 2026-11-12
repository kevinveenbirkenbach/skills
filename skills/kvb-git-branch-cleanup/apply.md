# Apply

1. Re-read `council.py list --long` and drop every item claimed since the dry run.
2. `--apply` refuses outside the host PID namespace (exit 2) and deletes
   remote branches, which is a push. Unless this session runs in the host PID
   namespace and the project lets agents push, hand the operator one command
   per repository, run from inside it, one `--branch` per picked item (the
   worktree path for a detached worktree), with the command of the skill that
   planned it:

   ```bash
   pkgmgr branch cleanup --apply --json --branch <name> --branch <name> | tee /tmp/branch-cleanup-apply-<N>.json
   ```

3. Read every item's `result` there: `done`, `done; image kept: <img>` (still
   in use elsewhere), `skipped: <why>` (changed since the plan or during the
   fini hook), or `failed: <why>`. Report a failure as it stands; never
   remove by hand what pkgmgr skipped or refused.
4. For every `done` item, drop its worktree and branch from the task listing
   them in the `kvb-org-rasci` register (`rasci.py artifacts` names it): `set
   <task> --drop-artifact worktree:<path>`, and `--branch ''` where the branch
   is gone.
