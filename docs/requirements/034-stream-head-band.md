# 034 - Stream Head Band

## User Story

As the operator, I want the stream's view buttons, search and filters in one
head band separated from the list, so that I see where the controls end and
the entries start.

## Decisions (operator-confirmed 2026-11-25; do not re-litigate)

1. **Head band** (operator pick 2026-11-25): the stream's top row (view
   buttons, search, filter menu, entry count) is the box head band of 023:
   flush under the box's top border, tinted like the other box heads, with a
   1 px line below it. Rejected: a plain 1 px line, which scrolls away and
   differs from the other box heads.
2. **Sticky**: the band stays at the top of the stream box while the list
   scrolls.
3. **Timing**: as 032.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["🧭 A · Head band"]
        A1["🧩 Filter row becomes the box head band"] --> A2["📌 Sticky while the list scrolls"]
        A2 --> A3["✍️ E2E test written"]
    end
    A3 --> C1
    subgraph C["🧪 C · All of 032 to 038"]
        C1["🧪 All tests once"] --> C2{"🟢 Green?"}
        C2 -- "🔴 no: fix" --> C1
        C2 -- "🟢 yes" --> CF{"💬 Operator feedback on screenshots?"}
        CF -- "✏️ changes" --> A1
    end
    CF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
```

## Acceptance Criteria

### Band

- [ ] The band is the first child of the stream box; its top edge equals the
      box's inner top edge (within 1 px).
- [ ] The band has a 1 px bottom border in `var(--line)` and the background
      of a Home widget, under which its title bar sits, so the list never
      shows through it.

### Sticky

- [ ] After the list scrolls by 600 px the band's top edge is unchanged
      (within 1 px).

### Tests

- [ ] Unit: n/a: layout only.
- [ ] Integration: n/a: no server change.
- [ ] E2E: band geometry and the scroll probe at 1920, 1366 and 390;
      screenshots.
