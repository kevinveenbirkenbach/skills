# 055 - WASD in Match

## User Story

As the operator, I want to swipe the Match deck with W, A, S and D in an
endless round with the release card coming up in between, so that I decide,
skip, undo and release without leaving the keyboard's home row.

## Decisions (operator-confirmed 2026-11-25; do not re-litigate)

1. **Keys** (operator): D accepts, A rejects, W skips to the next card, S goes
   back to the last card and undoes what happened to it: a decision is taken
   back, a skip is reversed. Each further S steps one action further back,
   down to the last release. The arrows keep working. Rejected: S undoing a
   single step only.
2. **Release card** (operator): the same keys work on the release card of
   040: D releases, A goes back to the stack, W skips on, S brings back the
   last card.
3. **Endless round** (operator): W cycles through every open card, greyed
   ones included, without end; while at least one decision waits, the
   release card is one place in that round and comes up once per lap.
4. **Precedence**: on the Match screen W, A, S and D go to the deck before
   any global key; in a text field they type as usual. The help (`?`) lists
   them.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["⌨️ A · WASD"]
        A1["🧩 Keys to accept, reject, skip"] --> A2["↩️ Undo stack for S"]
        A2 --> A3["🔁 Release card in the endless round"]
        A3 --> A4["✍️ E2E test written"]
    end
    A4 --> C1
    subgraph C["🧪 C · All of 039 to 055"]
        C1["🧪 All tests once"] --> C2{"🟢 Green?"}
        C2 -- "🔴 no: fix" --> C1
        C2 -- "🟢 yes" --> CF{"💬 Operator feedback on screenshots?"}
        CF -- "✏️ changes" --> A1
    end
    CF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
```

## Acceptance Criteria

### Keys

- [ ] D on the front card decides it as accept, A opens its reject feedback,
      W puts it at the back; the arrows still do the same.
- [ ] After D, W, D, three S bring back the cards in reverse order, the two
      decisions undone and the skipped card in front again.
- [ ] Typing W, A, S or D in a text field of the Match screen types the
      letter and moves no card.

### Round

- [ ] With one decision made and two open cards, pressing W cycles card,
      card, release card, card, and so on.
- [ ] On the release card D releases, A shows the stack, W shows the next
      card, S brings back the last card.

### Tests

- [ ] Unit: n/a: page JS.
- [ ] Integration: n/a: no server change.
- [ ] E2E: the Keys and Round checks in Chromium; screenshots.
