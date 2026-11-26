# 045 - Artifacts Head on One Line

## User Story

As the operator, I want the Artifacts head on one tidy line, so that the
controls and the status do not break apart.

## Decisions (operator-confirmed 2026-11-25; do not re-litigate)

1. **One line**: from 1024 px width, view switch, picker, toolbar and count
   sit on one line; no word breaks.
2. **Count**: "97 repositories · as of 14:02" truncates with an ellipsis
   when space runs short; the full text sits in `title`.
3. **Delete blocked**: leaves the count text and becomes a warning chip
   beside the delete button; chip and disabled delete button (042's
   wrapper) carry the reason as tooltip.
4. **Narrow**: below 1024 px at most two lines, still no word broken.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["🧱 A · Artifacts head"]
        A1["🧩 One-line head"] --> A2["⚠️ Delete-blocked chip"]
        A2 --> A3["✍️ E2E test written"]
    end
    A3 --> C1
    subgraph C["🧪 C · All of 039 to 046"]
        C1["🧪 All tests once"] --> C2{"🟢 Green?"}
        C2 -- "🔴 no: fix" --> C1
        C2 -- "🟢 yes" --> CF{"💬 Operator feedback on screenshots?"}
        CF -- "✏️ changes" --> A1
    end
    CF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
```

## Acceptance Criteria

### Head

- [ ] At 1920 and 1366 the Artifacts head is one line: its height equals a
      single control row (±2 px).
- [ ] The count element has `text-overflow: ellipsis` and a `title` with
      the full text.
- [ ] Without a GitHub token a warning chip beside the delete button names
      the reason and the count text holds no "Delete blocked".
- [ ] At 390 the head takes at most two lines.

### Tests

- [ ] Unit: n/a: page JS and CSS.
- [ ] Integration: n/a: no server change.
- [ ] E2E: the four checks above; screenshots at 1920, 1366 and 390.
