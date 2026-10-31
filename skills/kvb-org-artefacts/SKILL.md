---
name: kvb-org-artefacts
description: >
  Artifacts of the kvb-org-rasci register per task: images, volumes,
  worktrees. Trigger on /kvb-org-artefacts, "artefakte".
---

Artifacts live in the same table as the tasks of the `kvb-org-rasci`
register: each one belongs to exactly one task, carries its kind, reference
and the time it was recorded, and takes status and worker from its task. The
script is the register's `${CLAUDE_SKILL_DIR}/../kvb-org-rasci/scripts/rasci.py`.

```bash
rasci.py set <task> --artifact <kind>:<ref>
rasci.py set <task> --drop-artifact <kind>:<ref>
rasci.py artifacts [--ended] [--task <task>]
```

Kinds: `image:`, `container:`, `volume:`, `network:`, `stack:`, `worktree:`,
`dir:`, `log:`. `artifacts` lists each task's workdir and branch beside them.

## Rules

- Record an artifact the moment it exists, under the task that created it;
  one left unrecorded is invisible to cleanup.
- `artifacts --ended` lists what belongs to `done`, `stopped` or `stale`
  tasks: the cleanup candidates, owned by the task's worker. Everything of an
  open task stays.
- Deleting goes through the `kvb-cleanup` skill, where the operator picks;
  drop the artifact here once it is gone.
- The register's `show` counts each task's artifacts in its Artifacts column.
