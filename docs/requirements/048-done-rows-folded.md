# 048 - Done Rows Greyed and Folded

## User Story

As the operator, I want finished rows in Waits on Operator clearly greyed
and out of the way, without a checkbox, so that I see at a glance what still
waits on me.

## Decisions (operator-confirmed 2026-11-25; do not re-litigate)

1. **Done** means signed and inside its undo window (`held`) or its job
   ended. Such a row is greyed (opacity at most 0.5, grayscale), carries a
   "done" pill and moves under a "Done (n)" fold at the bottom, closed by
   default. Rejected: greyed in place; hidden at once, which leaves the undo
   window only in the toast.
2. **No checkbox** (operator: the green check already does it): in Select
   mode the selection shows as the highlighted row (`aria-selected="true"`)
   and the pressed green check; `x` still selects. Rejected: keeping the
   checkbox.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["🗂️ A · Done fold"]
        A1["🧩 Done rows greyed under a fold"] --> A2["☑️ Checkbox out, selection on the row"]
        A2 --> A3["✍️ E2E test written"]
    end
    A3 --> C1
    subgraph C["🧪 C · All of 039 to 050"]
        C1["🧪 All tests once"] --> C2{"🟢 Green?"}
        C2 -- "🔴 no: fix" --> C1
        C2 -- "🟢 yes" --> CF{"💬 Operator feedback on screenshots?"}
        CF -- "✏️ changes" --> A1
    end
    CF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
```

## Acceptance Criteria

### Done

- [ ] A held row and a row whose job ended lie in a closed
      `details.inbox-done` at the end of `#tasks/operator`, each with
      `data-done`, a "done" pill and a computed opacity of at most 0.5.
- [ ] Its summary reads "Done (n)" with n the number of such rows.

### Selection

- [ ] `.inbox-list .item` holds no `input[type="checkbox"]`.
- [ ] In Select mode the green check of a row sets `aria-selected="true"` on
      the row and `aria-pressed="true"` on the check; a second click clears
      both; `x` toggles the same.

### Tests

- [ ] Unit: n/a: page JS.
- [ ] Integration: the checkbox test in `test_hub_operator_tasks` becomes the
      selection check; `test_hub_grant_mode` follows.
- [ ] E2E: the Done and Selection checks at 1920 and 390; screenshots.
