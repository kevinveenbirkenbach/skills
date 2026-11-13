  const KANBAN_LABELS = {blocked: ["Blocked", "bad"], stopped: ["Stopped", "neutral"]};
  const KANBAN_COLUMN_ICONS = {queued: "bi-hourglass", running: "bi-play-circle", done: "bi-check2-circle"};
  const KANBAN_DRAG = "application/x-kvb-task";
  const kanban = {staged: [], collapsed: new Set(), old: false, dragging: null};

  function restage(next) {
    kanban.staged = next;
    taskView.sig = "";
    drawTasks();
  }

  function stageMove(task, targets) {
    const hub = state.tasks.find((row) => row.task === task);
    if (!hub) {
      return;
    }
    let next = kanban.staged;
    for (const target of targets.filter((entry) => (entry.column || entry.status ? hub.movable : hub.editable))) {
      next = Kanban.stage(next, hub, target, Kanban.pending(state.tasks, next));
    }
    restage(next);
  }

  async function applyStaged() {
    const changes = kanban.staged.map(({task, argv}) => ({task, argv}));
    if (changes.length && (await changeTasks(changes, `Apply ${changes.length} changes`, null))) {
      restage([]);
    }
  }

  function cardWhy(task) {
    const found = Kanban.why(state.jobs, task);
    if (!found) {
      return null;
    }
    const share = `${found.applied}/${found.total}`;
    const partly = found.applied ? h("span", {class: "pill kanban-partly", "data-tone": "warn", "data-partly": share, role: "img", ...named(`Partly applied: ${share}`, `${task}: ${found.applied} of the ${found.total} changes of the last batch applied, the others refused`)}, icon("bi-exclamation-diamond"), share) : null;
    return [partly, found.failed.map((job) => h("p", {class: "task-why", "data-job": job.id, title: job.command}, icon("bi-exclamation-triangle"), job.output.trim().split("\n").pop() || job.status))];
  }

  function menuItem(name, label, run, hint) {
    return h("button", {type: "button", class: "btn small ghost", ...named(label, hint), on: {click: (event) => {
      event.currentTarget.closest("details").open = false;
      run();
    }}}, icon(name), label);
  }

  function kanbanMenu(row, cards) {
    const columns = TASK_COLUMNS.map(([id, label]) => menuItem(KANBAN_COLUMN_ICONS[id], label, () => stageMove(row.task, [{column: id}]), `Move ${row.task} to ${label}`));
    const lanes = row.editable ? Kanban.LANES.map(([id, label]) => menuItem("bi-pin-angle", label, () => stageMove(row.task, [{lane: id}]), `Move ${row.task} to ${label}`)) : [];
    const others = cards.filter((other) => other.task !== row.task && !row.after.includes(other.task));
    const follow = row.editable && others.length ? h("select", {class: "field", ...named("Follows", `${row.task} follows the chosen task`), on: {change: (event) => stageMove(row.task, [{after: event.target.value}])}},
      h("option", {value: "", selected: true, disabled: true}, "…"), others.map((other) => h("option", {value: other.task}, other.task))) : null;
    const drops = row.editable ? row.after.map((task) => menuItem("bi-x-lg", task, () => stageMove(row.task, [{drop: task}]), `Remove: ${row.task} no longer follows ${task}`)) : [];
    return h("details", {class: "menu kanban-menu", on: {click: (event) => event.stopPropagation(), keydown: (event) => event.stopPropagation()}},
      h("summary", named("Move", `Move ${row.task}: column, lane and dependencies by keyboard`), icon("bi-three-dots-vertical")),
      h("div", {class: "menu-box"}, h("div", {class: "actions", role: "group", "aria-label": "Column"}, columns), lanes.length ? h("div", {class: "actions", role: "group", "aria-label": "Lane"}, lanes) : null, follow, drops.length ? h("div", {class: "actions", role: "group", "aria-label": "Follows"}, drops) : null));
  }

  function dragFrom(task, mode) {
    return (event) => {
      event.stopPropagation();
      kanban.dragging = {task, mode};
      event.dataTransfer.setData(KANBAN_DRAG, task);
      event.dataTransfer.effectAllowed = mode === "card" ? "move" : "link";
    };
  }

  function cardLabels(row) {
    const label = Kanban.labelOf(row);
    const stale = Plan.stale(row, state.now);
    const stop = stale && row.editable ? iconBtn("bi-stop-circle", "Stop", "btn small ghost kanban-stop", (event) => {
      event.stopPropagation();
      stageMove(row.task, [{status: "stopped"}]);
    }, `Stop ${row.task}: stage the status stopped`) : null;
    return [
      label ? h("span", {class: "pill", "data-tone": KANBAN_LABELS[label][1], "data-label": label}, KANBAN_LABELS[label][0]) : null,
      stale ? h("span", {class: "pill kanban-stale", "data-tone": "warn", "data-label": "stale"}, "Stale", stop) : null,
    ];
  }

  const cardOf = (task) => () => [...document.querySelectorAll("#main .kanban-card")].find((node) => node.dataset.task === task) || null;

  function kanbanCard(row, lane, column, cards) {
    const open = () => taskSelect(row.task, cardOf(row.task));
    const own = (event) => !event.target.closest("button, summary, details, select, .kanban-handle");
    const after = () => kanban.dragging && kanban.dragging.mode === "after" && kanban.dragging.task !== row.task;
    return h("li", {
      class: ["task-card", "kanban-card", row.pending ? "pending" : ""].filter(Boolean).join(" "), "data-task": row.task, "data-item": `task:${row.task}`, "data-lane": lane, "data-column": column, tabindex: 0,
      "data-pending": row.pending ? row.pending.map((argv) => argv.join(" ")).join("\n") : null, draggable: row.movable ? "true" : null,
      on: {
        click: (event) => own(event) && open(),
        keydown: (event) => {
          if ((event.key === "Enter" || event.key === " ") && event.target === event.currentTarget) {
            event.preventDefault();
            open();
          }
        },
        dragstart: dragFrom(row.task, "card"),
        dragend: () => {
          kanban.dragging = null;
        },
        dragover: (event) => after() && event.preventDefault(),
        drop: (event) => {
          if (after()) {
            event.preventDefault();
            event.stopPropagation();
            const from = kanban.dragging.task;
            kanban.dragging = null;
            stageMove(row.task, [{after: from}]);
          }
        },
      },
    },
    h("div", {class: "head-row", "data-star-slot": ""}, h("code", {class: "task-id"}, row.task), cardLabels(row), h("span", {class: "spacer"}),
      row.pending ? h("span", {class: "kanban-pending", role: "img", ...named("Staged", row.pending.map(shownArgv).join("\n"))}, icon("bi-pencil")) : null,
      openJobs(row.task).length ? h("span", {class: "kanban-wait", role: "img", ...named("At the runner", `${row.task}: a signed change waits for the runner`)}, icon("bi-hourglass-split")) : null,
      row.editable ? h("span", {class: "kanban-handle", role: "img", draggable: "true", ...named("Follows", `Drag onto the card that waits for ${row.task}`), on: {dragstart: dragFrom(row.task, "after"), dragend: () => {
        kanban.dragging = null;
      }}}, icon("bi-arrow-right-circle")) : null,
      row.movable ? kanbanMenu(row, cards) : null),
    h("span", {class: "kanban-title"}, titleOf(row)),
    row.worker !== "-" ? h("span", {class: "muted"}, row.worker) : null,
    cardWhy(row.task));
  }

  function kanbanCell(lane, column, label, cards) {
    const card = () => kanban.dragging && kanban.dragging.mode === "card";
    return h("ol", {class: "kanban-cell task-cards", "data-lane": lane.id, "data-column": column, "aria-label": `${lane.label} · ${label}`, on: {
      dragover: (event) => card() && event.preventDefault(),
      drop: (event) => {
        if (card()) {
          event.preventDefault();
          const task = kanban.dragging.task;
          kanban.dragging = null;
          stageMove(task, [{column}, {lane: lane.id}]);
        }
      },
    }}, lane.cells[column].map((row) => kanbanCard(row, lane.id, column, cards)));
  }

  function kanbanLane(lane, cards) {
    const open = !kanban.collapsed.has(lane.id);
    const id = `kanban-lane-${lane.id}`;
    const toggle = h("button", {type: "button", class: "lane-toggle", "aria-expanded": String(open), "aria-controls": id, title: `${lane.label}: ${open ? "collapse" : "expand"}`, on: {click: () => {
      if (open) {
        kanban.collapsed.add(lane.id);
      } else {
        kanban.collapsed.delete(lane.id);
      }
      taskView.sig = "";
      drawTasks();
    }}}, icon(open ? "bi-chevron-down" : "bi-chevron-right"), lane.label, counter(lane.count));
    return h("section", {class: "kanban-lane", "data-lane": lane.id, "data-open": String(open)}, toggle,
      h("div", {class: "kanban-cells", id, hidden: !open}, TASK_COLUMNS.map(([column, label]) => kanbanCell(lane, column, label, cards))));
  }

  function kanbanBar(hidden, stale) {
    const count = kanban.staged.length;
    const words = `Apply ${count} changes`;
    const apply = h("button", {type: "button", class: "btn small primary", id: "kanban-apply", disabled: count === 0, ...named(words, `${words}: one passkey signs every staged move, the runner applies them through rasci.py`), on: {click: applyStaged}}, icon("bi-check2-all"), counter(count));
    const discard = h("button", {type: "button", class: "btn small icon-only", id: "kanban-discard", disabled: count === 0, ...named("Discard", "Discard the staged moves"), on: {click: () => restage([])}}, icon("bi-x-circle"));
    const older = h("button", {type: "button", class: "btn small", id: "kanban-old", "aria-pressed": String(kanban.old), ...named("Older Done", `Done cards older than 24 h: ${hidden}, ${kanban.old ? "shown" : "hidden"}`), on: {click: () => {
      kanban.old = !kanban.old;
      taskView.sig = "";
      drawTasks();
    }}}, icon(kanban.old ? "bi-eye" : "bi-eye-slash"), counter(hidden));
    const stalled = h("span", {class: "pill", id: "kanban-stale", "data-tone": "warn", role: "img", ...named(`Stale: ${stale}`, `Stale: ${stale} tasks without a register change for ${Plan.STALE_DAYS} days, counted apart`)}, icon("bi-hourglass-bottom"), String(stale));
    const listed = count ? h("ol", {class: "kanban-staged", id: "kanban-staged", "aria-label": `${words}: the passkey signs exactly these`},
      kanban.staged.map(({task, argv}) => h("li", {"data-task": task}, h("code", {}, shownArgv(argv))))) : null;
    return [h("div", {class: "kanban-bar", role: "toolbar", "aria-label": "Board"}, apply, discard, older, stalled), listed];
  }

  function kanbanLines(box, rows) {
    const svg = box.querySelector("svg.kanban-lines");
    const base = box.getBoundingClientRect();
    const rectOf = (task) => {
      const node = [...box.querySelectorAll(".kanban-card")].find((card) => card.dataset.task === task);
      const found = node && node.getClientRects().length ? node.getBoundingClientRect() : null;
      return found && {x: found.left - base.left, y: found.top - base.top, w: found.width, h: found.height};
    };
    const centre = (r) => ({x: r.x + r.w / 2, y: r.y + r.h / 2});
    const rim = (r, toward) => {
      const c = centre(r);
      const [dx, dy] = [toward.x - c.x, toward.y - c.y];
      const scale = Math.min(dx ? r.w / 2 / Math.abs(dx) : Infinity, dy ? r.h / 2 / Math.abs(dy) : Infinity, 1);
      return {x: c.x + dx * scale, y: c.y + dy * scale};
    };
    const hub = new Map(state.tasks.map((row) => [row.task, row]));
    const {arrows, queue} = Kanban.lines(rows, state.queue_line);
    const marks = [];
    for (const {from, to} of arrows) {
      const [a, b] = [rectOf(from), rectOf(to)];
      if (a && b) {
        const [start, end] = [rim(a, centre(b)), rim(b, centre(a))];
        const d = `M${fixed(start.x)},${fixed(start.y)} L${fixed(end.x)},${fixed(end.y)}`;
        const staged = !(hub.has(to) && hub.get(to).after.includes(from));
        marks.push(s("g", {class: `kanban-arrow${staged ? " pending" : ""}`, "data-from": from, "data-to": to, on: {click: () => stageMove(to, [{drop: from}])}},
          s("title", {}, `${to} follows ${from}: click to remove`), s("path", {class: "kanban-hit", d}), s("path", {class: "kanban-link", d, "marker-end": "url(#kanban-tip)"})));
      }
    }
    const stops = queue.map(rectOf).filter(Boolean).map(centre);
    if (stops.length > 1) {
      marks.push(s("polyline", {class: "kanban-queue", "data-tasks": queue.filter((task) => rectOf(task)).join(" "), points: stops.map((at) => `${fixed(at.x)},${fixed(at.y)}`).join(" ")}, s("title", {}, "Queue order")));
    }
    svg.setAttribute("width", box.scrollWidth);
    svg.setAttribute("height", box.scrollHeight);
    svg.replaceChildren(s("defs", {}, s("marker", {id: "kanban-tip", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 8, markerHeight: 8, markerUnits: "userSpaceOnUse", orient: "auto"}, s("path", {class: "kanban-tip", d: "M0,0 L10,5 L0,10 z"}))), ...marks);
  }

  function kanbanBoard(shown) {
    const known = new Set(state.tasks.filter((row) => row.movable).map((row) => row.task));
    if (kanban.staged.some((change) => !known.has(change.task))) {
      kanban.staged = kanban.staged.filter((change) => known.has(change.task));
    }
    const ids = new Set(shown.map((row) => row.task));
    const rows = Kanban.pending(state.tasks, kanban.staged).filter((row) => ids.has(row.task) && Kanban.onBoard(row));
    const {lanes} = Kanban.board(rows, {now: state.now, old: kanban.old});
    const cards = lanes.flatMap((lane) => Object.values(lane.cells).flat());
    const head = h("div", {class: "kanban-head"}, TASK_COLUMNS.map(([id, label]) => h("h3", {class: "task-column group-title", "data-column": id}, icon(KANBAN_COLUMN_ICONS[id]), label,
      counter(cards.filter((row) => Kanban.columnOf(row) === id).length))));
    const box = h("div", {class: "kanban"}, head, lanes.map((lane) => kanbanLane(lane, cards)), s("svg", {class: "kanban-lines", "aria-hidden": "true"}));
    const watch = new ResizeObserver(() => (box.isConnected ? kanbanLines(box, cards) : watch.disconnect()));
    watch.observe(box);
    return h("div", {class: "kanban-box"}, kanbanBar(Kanban.board(rows, {now: state.now, old: false}).hidden, rows.filter((row) => Plan.stale(row, state.now)).length), box);
  }
