# 008 - Home Dashboard

## User Story

As the operator, I want to star any panel or item of the hub and arrange the
starred ones on a Home tab, so that I get my own overview of what matters to
me.

## Decisions (operator-confirmed 2026-11-13; do not re-litigate)

1. **Home tab**: a new first tab left of Stream (route `#home`); it becomes
   the start tab once at least one pin exists, otherwise Stream stays the
   start; an explicit hash wins.
2. **Star everywhere**: a star button on every panel (each chart, the
   stream, the radio log, kanban, gantt, burndown, task list, RASCI,
   ancestry, 3D, the agents list) and on every single item (message, task,
   artifact, agent card); pressing it again unpins. Rejected: panels only;
   panels and agent cards only.
3. **Panel registry**: every pinnable panel and item kind registers an id, a
   title and a render function that takes the tile size; Home renders tiles
   through it, live with the same data as the source view. Rejected: Home as
   saved route views (views are not built for small cells and share page
   state).
4. **Grid**: a classic 12-column CSS grid; a tile resizes from 1 to 12
   columns wide and 1 to 12 rows high by a handle and reorders by drag and by
   the arrow keys while focused; no layout library. Rejected: gridstack.js (a
   new dependency for what CSS grid does).
5. **Gone items**: a tile whose item no longer exists shows "gone" with an
   unpin button; it is never removed silently.
6. **Persistence**: pins, sizes and order live in the unsigned view store of
   007, capped at 64 pins.
7. **Order**: the registry, stars and grid may start at once against the
   view store contract of 007; persistence and e2e after 007 is on master.

## Approach

```mermaid
flowchart TD
    subgraph P["🧭 0 · Preparation"]
        P1["📋 Write requirement"] --> P2{"✅ Operator approves?"}
        P2 -- "✏️ corrections" --> P1
    end
    P2 -- "🤖 yes" --> A1
    subgraph A["⭐ A · Registry and stars"]
        A1["🧩 Panel registry, star on every panel and item"] --> A2{"🧪 Unit and integration green?"}
        A2 -- "🔴 no: fix" --> A1
    end
    A2 -- "🟢 yes, 007 on master" --> B1
    subgraph B["🏠 B · Home grid"]
        B1["🔲 12-column grid, resize, drag, keyboard, gone tiles, start tab"] --> B2{"🧪 E2E green?"}
        B2 -- "🔴 no: fix" --> B1
        B2 -- "🟢 yes" --> BF{"💬 Operator feedback on screenshots?"}
        BF -- "✏️ changes" --> B1
    end
    BF -- "👍 fits" --> D1["🏁 Review, commit with operator OK, hand-over"]
```

## Acceptance Criteria

### Stars

- [ ] The e2e count of registered panels and items without a star is 0
      across all tabs.
- [ ] Starring adds a tile on Home and unstarring removes it; the same
      layout shows in a second browser.
- [ ] A 65th pin is refused with a visible message.

### Grid

- [ ] A tile spans w of 12 columns; the handle changes w from 1 to 12 and h
      from 1 to 12.
- [ ] Drag and keyboard reorder work and persist.
- [ ] At 390 px width every tile spans all 12 columns.

### Tiles

- [ ] A pinned chart updates on the next poll like its source view.
- [ ] A pinned task deleted from the register shows "gone" and an unpin
      button.

### Start tab

- [ ] With no pins the hub opens on Stream, with one or more on Home; an
      explicit hash wins.

### More bookmarks (operator 2026-11-14)

- [ ] The hardware chart, the tokens chart and the combined overlay of
      Resources each carry exactly one star, uncovered, and none per
      series.
- [ ] A metric pin stores the chip selection of the moment it was starred:
      the chart, accumulated or not, and the series switched on (null while
      all are on); the hub refuses a metric pin without that view or with
      an unknown chart, an unsorted, repeated or oversized series list.
- [ ] Another selection is another pin: with only CPU on, the hardware star
      pins `metric:hardware/<digest>`, with all series on
      `metric:hardware/all`, and the star shows the pressed state of the
      selection shown now.
- [ ] A metric pin made with only CPU on draws only the CPU line on Home,
      after a reload too, while Resources shows all series again.
- [ ] A pin of the combined overlay draws the combined chart on Home with
      its right token axis and the burnup lines.
- [ ] The artifacts tree view, Agent priority and Waits on Operator each
      carry a star and pin as a live tile.
- [ ] Every repository, branch, worktree and artifact row of the artifacts
      tree carries a star; its pin shows that one element on Home.
- [ ] A row whose escaped id runs past 200 characters, such as an artifact
      of a worktree under `~/Repositories/.../.worktrees/...`, pins
      `<kind>#<digest>` instead, which Home resolves against the live tree,
      so its star is never disabled for the length of a real path.
- [ ] With more than 100 series switched on but not all, a chart star is
      disabled and names why, so no press ends in "Home not saved"; the hub
      refuses a metric pin whose id is not the one its view gives.
- [ ] The tree tile on Home is a read-only glance: no delete button; with
      no repository at all it says so instead of naming a filter.
- [ ] A star in a slot that a redraw moves keeps the keyboard focus; a tile
      keeps its scroll position when Home draws it again.
- [ ] The time labels of a resources chart never overlap, at 390 px too.
- [ ] A pinned single agent card and a pinned single artifact row show
      "gone" with an unpin button once the agent or the artifact
      disappears, and Home reads the tree again at most 30 s after it last
      did.
- [ ] Every view starred before keeps its star and pins as before.

### Tests

- [ ] Unit: registry lookup, layout validation, reorder math.
- [ ] Integration: `/api/view` accepts the pins schema and refuses an
      oversize or malformed one; a PATCH whose `expect` no longer matches
      the stored pins gets 409, so two tabs never overwrite each other.
- [ ] E2E: Chromium and Firefox at 1920, 1366 and 390: star and unstar,
      resize, reorder by drag and keyboard, the gone tile, the start tab;
      screenshots for the checkpoint.
- [ ] E2E (`tests/e2e/test_home_bookmarks_e2e.py`): Chromium and Firefox at
      1920, 1366 and 390: every new star exists and is uncovered, pins and
      renders live on Home; the CPU-only metric pin survives a reload; the
      combined pin shows combined mode; the single agent and artifact
      tiles show their element and then "gone"; a repository, a worktree,
      a core worktree and an artifact row on paths of real length pin,
      show that one element on Home, turn "gone" and unpin; unpin works.
