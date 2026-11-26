# 033 - Coherent Speak Box

## User Story

As the operator, I want the radio speak box to be one coherent control, so
that writing, recording and sending read as one piece in the Radio view and
as a Home widget.

## Decisions (operator-confirmed 2026-11-25; do not re-litigate)

1. **One frame** (operator pick 2026-11-25): Channel and To on top as one
   segmented row, the message textarea, and a footer row with Record on the
   left and the mic, the PTT split and the MAYDAY toggle on the right, all
   in one border and separated only by 1 px lines. Rejected: a messenger
   composer with recipient chips, a rounded pill and a round send button,
   which adds a second visual language beside the frames of 031 and 032.
2. **No extra labels**: no inner "Speak" heading where a box or widget title
   already names the box; no channel hint as a tooltip on the Channel select
   or the textarea (025's "no hint text" covers tooltips too).
3. **Fit**: in widget mode the box fills the widget body; the textarea takes
   the free height and the footer with PTT and MAYDAY stays fully visible at
   every widget size the Home grid allows.
4. **Behaviour unchanged**: hold-to-talk, the PTT test menu and the inline
   MAYDAY confirmation keep working as today.
5. **Timing**: as 032.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["📻 A · Speak box"]
        A1["🧩 One frame: channel row, textarea, footer"] --> A2["📐 Widget fit"]
        A2 --> A3["✍️ Unit and E2E tests written"]
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

### Frame

- [ ] One frame element holds the channel row, the textarea and the footer;
      the footer's children are Record, a spacer, the mic, the PTT split and
      the MAYDAY toggle in this order.
- [ ] Inside the frame the parts are divided by 1 px lines and draw no
      borders of their own.

### Labels

- [ ] No visible "Speak" text in the box apart from the box or widget title.
- [ ] No text of `CHANNEL_HINTS` (page-composer.js) reaches a `title`
      attribute inside the composer.

### Fit

- [ ] As a Home widget at every height from 3 to 8 rows and every width
      from 4 to 12 columns, the PTT split and the MAYDAY toggle lie fully
      inside the widget body.

### Behaviour

- [ ] Hold-to-talk, the test menu and the MAYDAY confirmation pass the
      existing composer tests.

### Tests

- [ ] Unit: the composer's DOM order and the absence of hint titles.
- [ ] Integration: n/a: no server change.
- [ ] E2E: Radio view and Home widget at 1920, 1366 and 390; geometry
      probes; screenshots.
