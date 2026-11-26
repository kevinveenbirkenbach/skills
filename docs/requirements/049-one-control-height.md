# 049 - One Control Height

## User Story

As the operator, I want every control in every head bar at one height, so
that buttons, search field and filters line up on every page.

## Decisions (operator-confirmed 2026-11-25; do not re-litigate)

1. **36 px** (operator pick) for every control in a `.box-head`: icon
   buttons, the search field with its mic, the filter button, chips and
   selects, from one CSS token. Rejected: 32 px, which shrinks the search
   field; 40 px, which grows every button.
2. **Design pass**: every view is screenshotted at 1920 and 390; each misfit
   found (alignment, wrapping, spacing) is fixed under this requirement and
   listed in the hand-over.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["📏 A · Control height"]
        A1["🧩 One height token"] --> A2["🔎 Design pass over every view"]
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

### Height

- [ ] `style-ui.css` defines `--control-h: 36px`, and every head-bar control
      rule uses it.
- [ ] In every view of `test_box_heads_e2e.py`, every visible control in
      `.box-head` is 36 ± 1 px high at 1920 and 390.
- [ ] Stream head: icon buttons, search field, filter button and count text
      share one vertical centre ± 1 px.

### Design pass

- [ ] The hand-over lists every misfit found with its fix and its
      before/after screenshot.

### Tests

- [ ] Unit: n/a: CSS.
- [ ] Integration: n/a: no server change.
- [ ] E2E: `test_box_heads_e2e.py` extended by the Height checks.
