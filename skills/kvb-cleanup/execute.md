# Executing the selection

- Right before each delete, re-check claims, open handles and running state:
  a peer may have started something since the inventory.
- Delete exactly the selected items, by name or path, never by a blanket
  prune (`docker system prune -a --volumes`, `rm -rf /tmp/*`). For more than
  a handful of paths, write the list to a file under `/tmp`, grep it against
  every claim once more, then `xargs -d '\n' rm -rf -- < <list>`; never
  `find -exec rm -rf`, which the classifier refuses.
- Never stop, take down or kill a running job to free space, nor ask its
  owner to: not for a priority slot, not at a disk stop. Free idle items, ask
  the operator for an exception, or wait; an owner's disk guard only alerts
  the chair; only the operator orders a running job down. A hung job is no
  cleanup item: the `kvb-org-organize` hang rule lets only its owner end it.
- Idle running stacks go down by the project's teardown target, never by
  removing their containers or volumes. Worktrees go as `worktrees.md` says.
- Archive-first items: copy out, verify the copy, then delete.
- Drop every deleted item from its task (`rasci.py set <task> --drop-artifact
  <kind>:<ref>`, see `kvb-org-artefacts`) so `artifacts` stays true.
- A host permission layer (auto-mode classifier, deny rule) may refuse a
  delete; never route around it by another command or a peer. Finish the
  rest, then offer the refused item to the operator again as its own option:
  an explicit renewed pick may pass; refused again, hand over the exact
  command with its list file.
- A delete failing on permissions (container-UID files) goes through the
  project's container helper, never sudo or a sandbox bypass; without a
  helper, report the path.
- Stop on the first unexpected error and report it.
