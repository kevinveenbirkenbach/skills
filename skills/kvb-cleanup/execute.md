# Executing the selection

- Re-check claims, open handles and running state right before each delete:
  a peer may have started something since the inventory.
- Delete exactly the selected items, by name or path. No blanket prune
  (`docker system prune -a --volumes`, `rm -rf /tmp/*`) that sweeps beyond
  the selection. For more than a handful of paths, write the list to a file
  under `/tmp`, grep it against every claim once more, then delete with
  `xargs -d '\n' rm -rf -- < <list>`.
- Never stop, take down or kill a running job, and never ask its owner to, to
  free space: not for a priority slot, not at a disk stop. Free idle items,
  ask the operator for an exception, or wait; an owner's own disk guard only
  alerts the chair, and only the operator can order a running job down. A
  hung job is not freed through cleanup: the `kvb-org-organize` hang rule
  lets only its owner end it.
- Idle running stacks go down through the project's teardown target, never by
  removing their containers or volumes underneath them. Worktrees go as
  `worktrees.md` says.
- Archive-first items: copy out, verify the copy, then delete.
- Drop every deleted item from its task as the `kvb-org-artefacts` skill says
  (`rasci.py set <task> --drop-artifact <kind>:<ref>`), so `artifacts` stays
  true.
- A host permission layer (an auto-mode classifier, a deny rule) may refuse a
  delete. Never route around it with another command or a peer. Finish the
  rest, then put the refused item to the operator again as its own option: an
  explicit renewed selection may pass; if it is refused again, hand over the
  exact command with its list file for the operator to run.
- A delete failing on permissions (files owned by a container UID): use the
  project's container helper. Never sudo, never bypass the sandbox; without a
  helper, report the path.
- Stop on the first unexpected error and report it.
