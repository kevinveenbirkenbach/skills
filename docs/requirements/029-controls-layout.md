# 029 - Controls Layout

## User Story

As the operator, I want the Controls tabs (Tools, Rules, Groups) laid out
like the other views, so that I find their forms at once and the settings
list shows what matters.

## Decisions (operator-confirmed 2026-11-23; do not re-litigate)

1. **Head**: Controls with its Tools, Rules and Groups switch sits in the
   023 box head, not floating beside the content.
2. **Width and alignment**: the Groups and Rule sets cards span the content
   width; form labels share one baseline; the mic button sits inside its
   field's end, as 031 builds it.
3. **Settings list**: files whose folder does not exist hide behind a "show
   N missing" toggle; rows with an error chip come first, then by path.
4. **Chips**: group members and set rules are checkbox chips (members with
   faces) instead of multi-select boxes; an empty rule list says how to
   create a rule.
5. **Timing**: 023 decision 5.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes, after 028" --> A1
    subgraph A["🎛️ A · Controls"]
        A1["🧱 Switch in the box head"] --> A2["📐 Full width, aligned labels, mic inside"]
        A2 --> A3["🗂️ Missing files folded, errors first"]
        A3 --> A4["☑️ Member and rule chips"]
        A4 --> A5["✍️ Unit and E2E tests written"]
    end
    A5 --> C1
    subgraph C["🧪 C · After 030"]
        C1["🧪 All tests of 023 to 030 once"] --> C2{"🟢 Green?"}
        C2 -- "🔴 no: fix" --> C1
        C2 -- "🟢 yes" --> CF{"💬 Operator feedback on screenshots?"}
        CF -- "✏️ changes" --> A1
    end
    CF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
```

## Acceptance Criteria

- [ ] On every Controls tab the switch sits in `.box-head` at the box's top
      edge.
- [ ] The Groups and Rule sets cards are as wide as the Rules card (within
      1 px).
- [ ] Per form all labels share one top offset (within 1 px); each mic
      button lies inside its field.
- [ ] With 40 fixture paths of which 30 lack their folder, the list shows
      10 rows and "show 30 missing", which reveals them; error rows first.
- [ ] Checking two member chips and saving signs a group of those two.
- [ ] `grep -n 'multiple' orchestrator/templates/page-rules.js` finds no
      multi-select.

### Tests

- [ ] Unit: settings list filter and order.
- [ ] Integration: n/a: the signed group and rule set APIs are unchanged.
- [ ] E2E: the layout probes and a group creation at 1920, 1366 and 390;
      screenshots.
