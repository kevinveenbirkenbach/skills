# 041 - Code Marks in the Review Modal

## User Story

As the operator, I want to mark code lines in the review modal's diff as I
can in Match, so that I point the agent at exact lines when I deny or
approve.

## Decisions (operator-confirmed 2026-11-25; do not re-litigate)

1. **Scope**: the review modal only. Rejected: every diff view, more surface
   than asked for.
2. **Mechanism**: Match's marking is reused, not rebuilt: select or click
   lines, attach a comment.
3. **Flow**: Deny prefills its reason with the marks as `path:line` plus
   comment; Approve sends them to the agent as notes by radio post, as
   Match does after a release.
4. **Persistence**: marks are kept per review id until the review is
   decided, like Match's marks.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["🖍️ A · Review marks"]
        A1["🧩 Match marking on the modal diff"] --> A2["📝 Marks into deny reason and approval notes"]
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

### Marks

- [ ] In the review modal, marking a diff line and adding the comment "c"
      shows the mark in the modal.
- [ ] Deny opens with a reason containing `<path>:<line>` and "c".
- [ ] Approve sends one radio post to the agent containing `<path>:<line>`
      and "c".
- [ ] Closing and reopening the modal for the same review keeps the mark.

### Tests

- [ ] Unit: n/a: page JS.
- [ ] Integration: n/a: no server change.
- [ ] E2E: the four checks above; screenshot.
