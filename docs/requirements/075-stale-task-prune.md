# 075 - Stale Task Prune

## User Story

As the operator, I want to prune stale tasks in one step, with the agents
able to object, so that the board stays clean.

## Decisions (operator-confirmed 2026-11-27; do not re-litigate)

1. **Stale** = an open task without a register change for N days and
   without a running mark (074); N starts at `Plan.STALE_DAYS` (3) and is
   set in the dialog (operator).
2. **Prune dialog** (operator): a checklist of the stale tasks, the days
   field and the answer deadline on the analog dial, 10 minutes to start
   with. The undo dial of `page-dial.js` is refactored into one dial
   component that both use.
3. **Announcement** (operator): on Prune one passkey assertion signs the
   list and the deadline, and the hub sends a Sécurité radio message to all
   that names every task and the deadline.
4. **Objection**: an agent keeps a task before the deadline with
   `rasci.py keep <task>`; any register change of the task counts as
   keeping it.
5. **Prune to stopped** (operator: option 1): at the deadline the runner
   sets every task nobody kept to stopped
   (`rasci.py set <task> --status stopped`); the register archive takes it
   after 7 days. Rejected: `rasci.py rm` (deleted for good).

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["🕰️ A · Dial"]
        A1["♻️ One dial component for undo and prune"] --> A2{"🧪 Undo tests still green?"}
        A2 -- "🔴 no: fix" --> A1
    end
    A2 -- "🟢 yes" --> B1
    subgraph B["🧹 B · Prune"]
        B1["📋 Dialog, signed list and deadline"] --> B2["📢 Sécurité message"]
        B2 --> B3["⏱️ Deadline: stop the unkept tasks"]
        B3 --> B4{"🧪 Unit, integration and E2E green?"}
        B4 -- "🔴 no: fix" --> B1
        B4 -- "🟢 yes" --> BF{"💬 Operator feedback on screenshots?"}
        BF -- "✏️ changes" --> B1
    end
    BF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
```

## Acceptance Criteria

### Dialog

- [ ] The dialog lists exactly the stale tasks for the chosen N.
- [ ] The deadline sits on the analog dial, and the dial counts down until
      it.

### Prune

- [ ] The Sécurité row names every task and the deadline.
- [ ] A task kept before the deadline stays open; every other listed task
      is stopped at the deadline.
- [ ] A task that was not in the signed list is never changed.

### Dial

- [ ] The undo dial and the prune dial are one component, and the undo
      tests pass unchanged.

### Tests

- Unit:
  - [ ] Stale selection, `rasci.py keep` and the deadline apply.
- Integration:
  - [ ] The signed prune job through the HTTP handler and the runner's
        argv.
- E2E:
  - [ ] `tests/e2e/test_stale_prune_e2e.py`: dialog, dial, countdown,
        screenshots at 1920, 1366 and 390.
