# 050 - Menus Stay Open

## User Story

As the operator, I want the filter menu to stay open while I click its
chips, so that I set several filters in one go.

## Decisions (operator-confirmed 2026-11-25; do not re-litigate)

1. **Stay open**: clicks inside the Stream filter menu, and inside every hub
   menu whose entries are toggle chips, never close it. A menu entry that
   runs an action still closes its menu.
2. **Close** (operator): 3 s after the pointer leaves the menu, cancelled when
   it comes back; at once on a click outside or Esc.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["📂 A · Menus"]
        A1["🧩 Chip clicks keep the menu"] --> A2["⏲️ Close 3 s after leave, outside click, Esc"]
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

### Menu

- [ ] After clicks on three kind chips of the Stream filter menu, the menu is
      open and all three chips show their new state.
- [ ] After the pointer leaves, the menu is open at 2.5 s and closed at
      3.5 s; a return at 2 s keeps it open.
- [ ] A click outside or Esc closes it at once.

### Tests

- [ ] Unit: n/a: page JS.
- [ ] Integration: n/a: no server change.
- [ ] E2E: the Menu checks in Chromium; screenshots.
