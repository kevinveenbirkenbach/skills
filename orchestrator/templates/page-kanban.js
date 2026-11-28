  const KANBAN_LABELS = {blocked: "Blocked", stopped: "Stopped"};
  const KANBAN_COLUMN_ICONS = {queued: "bi-hourglass", running: "bi-play-circle", done: "bi-check2-circle"};
  const KANBAN_DRAG = "application/x-kvb-task";
  const KANBAN_LAYERS = "kanban.hidden";
  const KANBAN_JOBS_SHOWN = 3;
  const KANBAN_STATES = [
    {key: "running", tone: "ok", line: "solid", label: "Running", states: ["running", "claimed"]},
    {key: "operator", tone: "warn", line: "solid", label: "Waits on the operator: an open card of its owner waits for an answer", states: ["operator"]},
    {key: "queued", tone: "info", line: "solid", label: "Queued or waiting for a grant", states: ["queued", "awaiting"]},
    {key: "blocked", tone: "bad", line: "solid", label: "Blocked, or a queue job that failed", states: ["blocked", "failed"]},
    {key: "stale", tone: "faint", line: "dashed", label: `Stale: no register change for ${Plan.STALE_DAYS} days`, states: ["stale"]},
    {key: "ended", tone: "line-strong", line: "solid", label: "Ended: done or stopped", states: ["done", "stopped"]},
  ];
  const kanban = {staged: [], collapsed: new Set(), old: false, running: false, stale: false, marks: {}, waiting: new Set(), dragging: null, queue: {marks: {}, line: true, jobs: true}, bound: false, bar: null};

  const queueFailed = (row) => row.kind === "queue" && row.queue !== null && typeof row.queue.exit === "number" && row.queue.exit !== 0;

  /**
   * @param row - a card's task row.
   * @returns {string} its owner: the worker, else the first R holder, else "".
   */
  const cardOwner = (row) => (row.worker && row.worker !== "-" ? row.worker : (Object.entries(row.roles || {}).find(([, letters]) => letters.includes("R")) || [""])[0]);

  /**
   * @param row - a card's task row, staged changes applied.
   * @param found - {operator, stale, working}: whether an open card of its owner waits on the operator, whether
   * Plan.stale counts it and whether it carries the heartbeat (taskWorking).
   * @returns {Object} the card's KANBAN_STATES entry. An ended row reads failed for a queue job that ended with a
   * non-zero exit, else its status; an open row waits on the operator, else is blocked, else stale unless it works,
   * else its status. A status no entry lists reads as queued, as the hub reads a row without one.
   */
  function cardState(row, found) {
    const open = found.operator ? "operator" : row.status === "blocked" ? "blocked" : found.stale && !found.working ? "stale" : row.status;
    const key = row.ended ? (queueFailed(row) ? "failed" : row.status) : open;
    return KANBAN_STATES.find((entry) => entry.states.includes(key)) || KANBAN_STATES.find((entry) => entry.states.includes("queued"));
  }

  /**
   * @param {Element} node a card or a legend swatch.
   * @param {Object} entry its KANBAN_STATES entry.
   * @returns {Element} node with --card-state set to the entry's theme token and --card-line to its border style.
   */
  function stateTint(node, entry) {
    node.style.setProperty("--card-state", `var(--${entry.tone})`);
    node.style.setProperty("--card-line", entry.line);
    return node;
  }

  function stateLegend() {
    return h("div", {class: "legend kanban-legend", "data-legend-slot": "", role: "group", "aria-label": "Card colours"}, KANBAN_STATES.map((entry) =>
      h("span", {class: "kanban-key", "data-card-state": entry.key}, stateTint(h("i", {class: "kanban-swatch", "aria-hidden": "true"}), entry), entry.label)));
  }

  function ownerFace(row, owner) {
    const nobody = () => h("span", {class: "avatar kanban-nobody", role: "img", ...named("No owner", `${row.task}: no worker and no R holder`)}, icon("bi-person-circle"));
    return h("span", {class: "kanban-owner", "data-owner": owner}, owner ? agentFace(owner, false) : nobody());
  }

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

  function cardLabels(row, stale) {
    const label = Kanban.labelOf(row);
    const stop = stale && row.editable ? iconBtn("bi-stop-circle", "Stop", "btn small ghost kanban-stop", (event) => {
      event.stopPropagation();
      stageMove(row.task, [{status: "stopped"}]);
    }, `Stop ${row.task}: stage the status stopped`) : null;
    return [
      label ? h("span", {class: "pill", "data-tone": "neutral", "data-label": label}, KANBAN_LABELS[label]) : null,
      stale ? h("span", {class: "pill kanban-stale", "data-tone": "neutral", "data-label": "stale"}, "Stale", stop) : null,
    ];
  }

  const cardOf = (task) => () => [...document.querySelectorAll("#main .kanban-card")].find((node) => node.dataset.task === task) || null;

  function whyButton(task, id) {
    const card = cardOf(task)();
    return card ? [...card.querySelectorAll(".queue-why")].find((node) => node.dataset.job === id) || null : null;
  }

  function openWhy(task, job) {
    const found = Kanban.whyHere(job);
    const anchor = () => whyButton(task, job.id);
    const body = h("div", {class: "popup-body"}, h("ol", {class: "queue-trace", "aria-label": `Rule trace of ${job.id}`}, found.steps.map((step) => h("li", {}, step))),
      job.reason && job.trace.length ? h("p", {class: "queue-reason"}, `Now: ${job.reason}`) : null);
    openPopup(found.label, [popupHead(icon("bi-signpost-split"), found.label, h("code", {class: "task-id"}, job.task || task)), body], anchor, () => {
      const button = anchor();
      if (button) {
        button.focus();
      }
    });
    const close = popupBox().querySelector(".popup-head button");
    if (close) {
      close.focus();
    }
  }

  function queuePlace(row) {
    const mark = kanban.queue.marks[row.task];
    if (!kanban.queue.line || !mark || mark.place === null) {
      return null;
    }
    return h("span", {class: "queue-place", "data-place": mark.place, role: "img", ...named(`Queue stop ${mark.place} of ${mark.of}`, `${row.task}: stop ${mark.place} of ${mark.of} on the queue line, in grant order`)}, String(mark.place));
  }

  function chipHint(job, chip) {
    if (chip.key === "waited") {
      return `${chip.hint}, since ${absolute.format(stampOf(state.now - job.waited_s))}`;
    }
    return chip.key === "eta" && job.eta_s !== null ? `${chip.hint}, about ${absolute.format(stampOf(state.now + job.eta_s))}` : chip.hint;
  }

  function queueJob(row, job) {
    const chips = Kanban.jobChips(job).map((chip) => h("span", {class: "pill queue-chip", "data-chip": chip.key, "data-tone": chip.tone, title: chipHint(job, chip)}, chip.text));
    const open = (event) => {
      event.stopPropagation();
      openWhy(row.task, job);
    };
    const hint = `Why ${job.id} stands at ${Kanban.whyHere(job).place}: the rules queue.py applied, in order`;
    const why = h("button", {type: "button", class: "btn small ghost queue-why", "data-job": job.id, ...named(`Why here: ${job.id}`, hint), on: {click: open}}, icon("bi-question-circle"), h("span", {class: "queue-why-text"}, "Why here?"));
    return h("li", {class: job.status === "active" ? "queue-job is-working" : "queue-job", "data-job": job.id, "data-class": job.class || "", "data-kind": job.kind},
      h("div", {class: "queue-chips"}, chips, why, job.status === "waiting" ? startNow(job) : null), job.reason ? h("p", {class: "queue-reason", title: job.reason}, job.reason) : null);
  }

  function queueJobs(row) {
    const mark = kanban.queue.marks[row.task];
    if (!kanban.queue.jobs || !mark || !mark.jobs.length) {
      return null;
    }
    const more = mark.jobs.length - KANBAN_JOBS_SHOWN;
    return h("ul", {class: "queue-jobs", "aria-label": `Queue jobs of ${row.task}`}, mark.jobs.slice(0, KANBAN_JOBS_SHOWN).map((job) => queueJob(row, job)),
      more > 0 ? h("li", {class: "queue-more muted"}, `+${more} more queue jobs`) : null);
  }

  function kanbanCard(row, lane, column, cards) {
    const open = () => taskSelect(row.task, cardOf(row.task));
    const own = (event) => !event.target.closest("button, summary, details, select, .kanban-handle");
    const after = () => kanban.dragging && kanban.dragging.mode === "after" && kanban.dragging.task !== row.task;
    const found = kanban.marks[row.task];
    const working = taskWorking(row, found);
    const stale = Plan.stale(row, state.now);
    const owner = cardOwner(row);
    const look = cardState(row, {operator: Boolean(owner) && kanban.waiting.has(agentKey(owner)), stale, working});
    return stateTint(h("li", {
      class: ["task-card", "kanban-card", row.pending ? "pending" : "", working ? "is-working" : ""].filter(Boolean).join(" "), "data-task": row.task, "data-item": `task:${row.task}`, "data-lane": lane, "data-column": column, tabindex: 0,
      "data-card-state": look.key, title: `${row.task}: ${look.label}`,
      "data-mark": found.length ? found[0].key : null, "data-marks": found.length ? found.map((mark) => mark.key).join(" ") : null,
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
    ownerFace(row, owner),
    h("div", {class: "head-row"}, queuePlace(row), h("code", {class: "task-id"}, row.task), cardLabels(row, stale), h("span", {class: "spacer"}),
      row.pending ? h("span", {class: "kanban-pending", role: "img", ...named("Staged", row.pending.map(shownArgv).join("\n"))}, icon("bi-pencil")) : null,
      openJobs(row.task).length ? h("span", {class: "kanban-wait", role: "img", ...named("At the runner", `${row.task}: a signed change waits for the runner`)}, icon("bi-hourglass-split")) : null,
      row.editable ? h("span", {class: "kanban-handle", role: "img", draggable: "true", ...named("Follows", `Drag onto the card that waits for ${row.task}`), on: {dragstart: dragFrom(row.task, "after"), dragend: () => {
        kanban.dragging = null;
      }}}, icon("bi-arrow-right-circle")) : null,
      row.movable ? kanbanMenu(row, cards) : null),
    h("span", {class: "kanban-title"}, titleOf(row)),
    markChips(row, found),
    row.worker !== "-" ? h("span", {class: "muted"}, row.worker) : null,
    queueJobs(row),
    cardWhy(row.task)), look);
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

  /**
   * @param {number} hidden the Done cards older than 24 h.
   * @param {number} stale the shown cards Plan.stale counts.
   * @param {number} marked the shown cards with a running mark.
   * @returns {Object} bar: the board's controls in three groups by data-tools:
   * "status" (the stale count while there is one, the prune countdown while one waits), "filters" (Running, Stale,
   * Older Done, the queue layers) and "actions" (Apply, Discard, Prune stale); a Home tile shows the bar in its head,
   * the Tasks toolbar moves each group into its place. listed: the staged moves, null without any.
   */
  function kanbanBar(hidden, stale, marked) {
    const count = kanban.staged.length;
    const words = `Apply ${count} changes`;
    const redraw = () => {
      taskView.sig = "";
      drawTasks();
    };
    const apply = h("button", {type: "button", class: "btn small primary", id: "kanban-apply", disabled: count === 0, ...named(words, `${words}: one passkey signs every staged move, the runner applies them through rasci.py`), on: {click: applyStaged}}, icon("bi-check2-all"), h("span", {class: "tool-word"}, "Apply"), counter(count));
    const discard = h("button", {type: "button", class: "btn small", id: "kanban-discard", disabled: count === 0, ...named("Discard", "Discard the staged moves"), on: {click: () => restage([])}}, icon("bi-x-circle"), h("span", {class: "tool-word"}, "Discard"));
    const flipOld = () => {
      kanban.old = !kanban.old;
      redraw();
    };
    const flipStale = () => {
      kanban.stale = !kanban.stale;
      redraw();
    };
    const older = h("button", {type: "button", class: "btn small", id: "kanban-old", "aria-pressed": String(kanban.old), ...named("Older Done", `Done cards older than 24 h: ${hidden}, ${kanban.old ? "shown" : "hidden"}`), on: {click: flipOld}}, icon(kanban.old ? "bi-eye" : "bi-eye-slash"), h("span", {class: "tool-word"}, "Older Done"), counter(hidden));
    const only = h("button", {type: "button", class: "btn small", id: "kanban-stale-only", "aria-pressed": String(kanban.stale), ...named("Stale", `Stale: ${stale} cards without a register change for ${Plan.STALE_DAYS} days, ${kanban.stale ? "only these shown" : "every card shown"}`), on: {click: flipStale}}, icon("bi-hourglass-bottom"), h("span", {class: "tool-word"}, "Stale"), counter(stale));
    const stalled = stale ? h("span", {class: "pill", id: "kanban-stale", "data-key": "kanban-stale", "data-tone": "warn", role: "img", ...named(`Stale: ${stale}`, `Stale: ${stale} tasks without a register change for ${Plan.STALE_DAYS} days, counted apart`)}, icon("bi-hourglass-bottom"), String(stale)) : null;
    const prune = pruneControls(stale);
    const tools = (key, label, nodes) => h("div", {class: "kanban-tools", "data-tools": key, role: "group", "aria-label": label}, nodes);
    const listed = count ? h("ol", {class: "kanban-staged", id: "kanban-staged", "aria-label": `${words}: the passkey signs exactly these`},
      kanban.staged.map(({task, argv}) => h("li", {"data-task": task}, h("code", {}, shownArgv(argv))))) : null;
    const bar = h("div", {class: "kanban-bar", role: "toolbar", "aria-label": "Board"}, tools("status", "Board status", [stalled, prune.chip]),
      tools("filters", "Board filters", [runningToggle(marked), only, older, queueLegend()]), tools("actions", "Board actions", [apply, discard, prune.open]));
    return {bar, listed};
  }

  function queueLegend() {
    const layers = LegendChips.render(Kanban.QUEUE_LAYERS.map(([id, label, tone]) => ({id, label, tone})), KANBAN_LAYERS, "hidden");
    const words = "The installed queue.py lists no JSON (queue.py list --json): the board numbers the grant order but shows no class, gate, ETA or rule trace";
    const only = state.queue_jobs === null && state.queue_line.length ? h("span", {class: "pill", id: "kanban-queue-order", "data-tone": "warn", role: "img", ...named("Queue order only", words)}, icon("bi-info-circle"), "Order only") : null;
    return [layers, only];
  }

  function bindLayers() {
    if (!kanban.bound) {
      kanban.bound = true;
      ViewStore.on(KANBAN_LAYERS, () => {
        taskView.sig = "";
        drawTasks();
      });
    }
  }

  function kanbanLines(box, rows) {
    const svg = box.querySelector("svg.kanban-lines");
    const base = box.getBoundingClientRect();
    const rectIn = (node) => {
      const found = node && node.getClientRects().length ? node.getBoundingClientRect() : null;
      return found && {x: found.left - base.left, y: found.top - base.top, w: found.width, h: found.height};
    };
    const cardNode = (task) => [...box.querySelectorAll(".kanban-card")].find((card) => card.dataset.task === task) || null;
    const rectOf = (task) => rectIn(cardNode(task));
    const stopOf = (task) => {
      const card = cardNode(task);
      return rectIn(card && card.querySelector(".queue-place")) || rectIn(card);
    };
    const centre = (r) => ({x: r.x + r.w / 2, y: r.y + r.h / 2});
    const rim = (r, toward) => {
      const c = centre(r);
      const [dx, dy] = [toward.x - c.x, toward.y - c.y];
      const scale = Math.min(dx ? r.w / 2 / Math.abs(dx) : Infinity, dy ? r.h / 2 / Math.abs(dy) : Infinity, 1);
      return {x: c.x + dx * scale, y: c.y + dy * scale};
    };
    const hub = new Map(state.tasks.map((row) => [row.task, row]));
    const {arrows, queue} = Kanban.lines(rows, kanban.queue.line ? state.queue_line : []);
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
    const stops = queue.map(stopOf).filter(Boolean).map(centre);
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
    const placed = Kanban.pending(state.tasks, kanban.staged).filter((row) => ids.has(row.task) && Kanban.onBoard(row));
    const sources = markSources();
    kanban.marks = Object.fromEntries(placed.map((row) => [row.task, Kanban.marks(row, sources)]));
    kanban.waiting = new Set(openInbox().filter((item) => !item.until && item.agent).map((item) => agentKey(item.agent)));
    const marked = placed.filter((row) => kanban.marks[row.task].length);
    const running = kanban.running ? marked : placed;
    const stale = running.filter((row) => Plan.stale(row, state.now));
    const rows = kanban.stale ? stale : running;
    bindLayers();
    kanban.queue = {marks: Kanban.queued(rows, state.queue_line, state.queue_jobs), ...Kanban.layers(ViewStore.get(KANBAN_LAYERS))};
    const {lanes} = Kanban.board(rows, {now: state.now, old: kanban.old});
    const cards = lanes.flatMap((lane) => Object.values(lane.cells).flat());
    const head = h("div", {class: "kanban-head"}, TASK_COLUMNS.map(([id, label]) => h("h3", {class: "task-column group-title", "data-column": id}, icon(KANBAN_COLUMN_ICONS[id]), label,
      counter(cards.filter((row) => Kanban.columnOf(row) === id).length))));
    const box = h("div", {class: "kanban"}, head, lanes.map((lane) => kanbanLane(lane, cards)), s("svg", {class: "kanban-lines", "aria-hidden": "true"}));
    const watch = new ResizeObserver(() => (box.isConnected ? kanbanLines(box, cards) : watch.disconnect()));
    watch.observe(box);
    const {bar, listed} = kanbanBar(Kanban.board(rows, {now: state.now, old: false}).hidden, stale.length, marked.length);
    kanban.bar = bar;
    return h("div", {class: "kanban-box"}, listed, stateLegend(), box);
  }
