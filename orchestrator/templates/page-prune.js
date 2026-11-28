  const PRUNE_TICK = 1000;
  const pruneView = {days: Prune.STALE_DAYS, ticked: new Set(), filter: "", collapsed: new Set(), dial: null, timer: null};

  const pruneNow = () => Date.now() / 1000;
  const pruneClock = (epoch) => new Date(epoch * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  const pruneStale = () => Prune.stale(state.tasks, markSources(), pruneView.days);

  function pruneTick() {
    const pending = Prune.pending(state.jobs || [], pruneNow());
    if (pending) {
      for (const left of document.querySelectorAll(".prune-left")) {
        left.textContent = Dial.countdown(pending.left);
      }
    } else {
      window.clearInterval(pruneView.timer);
      pruneView.timer = null;
    }
  }

  function pruneTicking() {
    if (pruneView.timer === null) {
      pruneView.timer = window.setInterval(pruneTick, PRUNE_TICK);
    }
  }

  /**
   * @param {number} stale how many cards Plan.stale counts on the board.
   * @returns {Object} open: the Prune stale entry of the Actions menu, which opens
   * the prune dialog and, while a signed prune waits for its deadline, shows the countdown; chip: for that wait the
   * compact countdown chip of the toolbar naming its tasks and deadline, else null.
   */
  function pruneControls(stale) {
    const pending = Prune.pending(state.jobs || [], pruneNow());
    const left = pending ? Dial.countdown(pending.left) : "";
    const hint = pending ? `Prune stale: signed, stops ${pending.tasks.join(", ")} at ${pruneClock(pending.deadline)}; opens the countdown` : "Prune stale tasks: one passkey signs the list and a deadline; the agents can keep a task until then";
    const open = h("button", {type: "button", class: "btn small", id: "kanban-prune-open", disabled: !stale && !pending, ...named("Prune stale", hint)},
      icon("bi-scissors"), h("span", {class: "tool-word"}, "Prune stale"), pending ? h("span", {class: "prune-left"}, left) : null);
    open.addEventListener("click", openPrune);
    if (!pending) {
      return {open, chip: null};
    }
    pruneTicking();
    const words = `Prune at ${pruneClock(pending.deadline)}: ${pending.tasks.join(", ")}`;
    const chip = h("span", {class: "pill prune-chip", id: "kanban-prune", "data-key": "kanban-prune", "data-tone": "warn", "data-deadline": String(pending.deadline), role: "timer", ...named(`Prune in ${left}`, words)},
      icon("bi-hourglass-split"), h("span", {class: "prune-left"}, left));
    return {open, chip};
  }

  const pruneChosen = (rows) => rows.filter((row) => pruneView.ticked.has(row.task) && Prune.matches(row, pruneView.filter)).map((row) => row.task);

  /**
   * @param {Object} dom the open dialog: {groups, rows, none, count, go}.
   * Brings every row and group in line with pruneView: rows outside the filter hidden, each row's tick, each group's
   * count of shown rows and its checkbox (checked when every shown row is ticked, indeterminate when some are), and
   * "Prune N" with N the ticked rows the filter shows.
   */
  function pruneSync(dom) {
    const shown = new Set(dom.rows.filter((row) => Prune.matches(row, pruneView.filter)).map((row) => row.task));
    for (const item of dom.groups.querySelectorAll("li[data-task]")) {
      item.hidden = !shown.has(item.dataset.task);
      item.querySelector("input[type=checkbox]").checked = pruneView.ticked.has(item.dataset.task);
    }
    for (const section of dom.groups.querySelectorAll(".prune-group")) {
      const tasks = [...section.querySelectorAll("li[data-task]")].map((item) => item.dataset.task).filter((task) => shown.has(task));
      const ticked = tasks.filter((task) => pruneView.ticked.has(task)).length;
      const all = section.querySelector(".prune-group-check");
      section.hidden = !tasks.length;
      section.querySelector(".prune-group-head .count").textContent = String(tasks.length);
      all.checked = tasks.length > 0 && ticked === tasks.length;
      all.indeterminate = ticked > 0 && ticked < tasks.length;
    }
    if (dom.none) {
      dom.none.hidden = shown.size > 0;
    }
    const chosen = pruneChosen(dom.rows).length;
    dom.count.textContent = String(chosen);
    dom.go.disabled = !chosen;
  }

  function pruneRow(row, dom) {
    const owner = Prune.owner(row);
    const days = Math.floor((state.now - row.updated) / 86400);
    return h("li", {"data-task": row.task}, h("label", {class: "check"},
      h("input", {type: "checkbox", checked: pruneView.ticked.has(row.task), "aria-label": `Prune ${row.task}`, on: {change: (event) => {
        if (event.target.checked) {
          pruneView.ticked.add(row.task);
        } else {
          pruneView.ticked.delete(row.task);
        }
        pruneSync(dom);
      }}}),
      h("span", {class: "prune-owner", title: owner === "-" ? "No owner" : revealed(owner)}, face(owner, false)),
      h("code", {class: "task-id"}, row.task),
      h("span", {class: "pill prune-age", "data-tone": "neutral", title: `No register change for ${days} days`}, `${days} d`)));
  }

  function pruneGroup(group, dom) {
    const open = !pruneView.collapsed.has(group.prefix);
    const id = `prune-group-${group.prefix}`;
    const list = h("ul", {class: "prune-list", id, hidden: !open, "aria-label": `${group.prefix} tasks`}, group.rows.map((row) => pruneRow(row, dom)));
    const all = h("input", {type: "checkbox", class: "prune-group-check", "aria-label": `Prune every shown ${group.prefix} task`, on: {change: (event) => {
      for (const item of list.querySelectorAll("li[data-task]:not([hidden])")) {
        if (event.target.checked) {
          pruneView.ticked.add(item.dataset.task);
        } else {
          pruneView.ticked.delete(item.dataset.task);
        }
      }
      pruneSync(dom);
    }}});
    const toggle = h("button", {type: "button", class: "prune-group-toggle", "aria-expanded": String(open), "aria-controls": id, title: `${group.prefix}: ${open ? "collapse" : "expand"}`, on: {click: () => {
      const opening = list.hidden;
      if (opening) {
        pruneView.collapsed.delete(group.prefix);
      } else {
        pruneView.collapsed.add(group.prefix);
      }
      list.hidden = !opening;
      toggle.setAttribute("aria-expanded", String(opening));
      toggle.title = `${group.prefix}: ${opening ? "collapse" : "expand"}`;
      toggle.firstChild.replaceWith(icon(opening ? "bi-chevron-down" : "bi-chevron-right"));
    }}}, icon(open ? "bi-chevron-down" : "bi-chevron-right"), h("span", {class: "prune-prefix"}, `${group.prefix}/`), counter(group.rows.length));
    return h("section", {class: "prune-group", "data-key": `prune-group:${group.prefix}`, "data-group": group.prefix},
      h("div", {class: "prune-group-head"}, all, toggle), list);
  }

  /**
   * @param {Object} dom the open dialog: {groups, rows, none, count, go}.
   * Lists the stale tasks for pruneView.days in one section per prefix, dropping ticks of tasks no longer stale;
   * fadeSwap() fades the rows that leave.
   */
  function pruneRender(dom) {
    dom.rows = pruneStale();
    const tasks = new Set(dom.rows.map((row) => row.task));
    pruneView.ticked = new Set([...pruneView.ticked].filter((task) => tasks.has(task)));
    dom.none = dom.rows.length ? h("p", {class: "muted prune-none", hidden: true}, "No stale task matches the filter.") : null;
    const nodes = dom.rows.length ? [...Prune.groups(dom.rows).map((group) => pruneGroup(group, dom)), dom.none]
      : [h("p", {class: "muted"}, `No task without a register change for ${pruneView.days} days.`)];
    fadeSwap(dom.groups, nodes, (box, swap) => {
      swap();
      pruneSync(dom);
    });
  }

  function pruneDays(dom, field) {
    const days = Prune.daysOf(field.value);
    field.setAttribute("aria-invalid", String(days === null));
    if (days !== null) {
      pruneView.days = days;
      pruneView.ticked = new Set(pruneStale().map((row) => row.task));
      pruneRender(dom);
    }
  }

  function pruneStepper(dom) {
    const field = h("input", {class: "field", type: "number", inputmode: "numeric", min: Prune.DAYS.min, max: Prune.DAYS.max, step: 1, id: "prune-days", value: String(pruneView.days), "aria-label": "Days without a register change", on: {change: () => pruneDays(dom, field)}});
    const step = (by, glyph, label) => h("button", {type: "button", class: "btn small icon-only", ...named(label, `${label}: the stale age, ${Prune.DAYS.min} to ${Prune.DAYS.max} days`), on: {click: () => {
      field.value = String(Math.min(Prune.DAYS.max, Math.max(Prune.DAYS.min, pruneView.days + by)));
      pruneDays(dom, field);
    }}}, icon(glyph));
    return h("div", {class: "prune-days"}, h("label", {class: "muted", for: "prune-days"}, "Stale after days"),
      h("span", {class: "prune-stepper"}, step(-1, "bi-dash-lg", "One day less"), field, step(1, "bi-plus-lg", "One day more")));
  }

  async function signPrune(body) {
    const tasks = pruneChosen(pruneStale());
    const since = Math.floor(pruneNow());
    const items = Prune.items(tasks, pruneView.days, since, pruneView.dial.value());
    const label = `Prune ${tasks.length} stale tasks`;
    const signed = await proofFor(items, label);
    if (signed === null) {
      return;
    }
    const result = await sendJson("/api/prune", {items, proof: signed.proof});
    toast(result.ok ? label : `${label}: not queued`, result.ok ? [`Sécurité now, stopped at ${pruneClock(since + pruneView.dial.value() * Prune.MINUTE)} unless kept`] : fail(result), result.ok);
    if (result.ok) {
      await load();
      taskView.sig = "";
      drawTasks();
      drawPrune(body);
    }
  }

  function pruneCountdown(body, pending) {
    pruneView.dial = dial({value: Math.ceil(pending.left / Prune.MINUTE), label: "Minutes until the prune", name: "prune-dial", min: 0, max: Prune.MINUTES.max, page: Prune.MINUTES.page,
      readout: (minutes) => Dial.countdown(minutes * Prune.MINUTE), spoken: (minutes) => `${minutes} minutes until the prune`, readonly: true, live: Dial.counting(pending.deadline, Prune.MINUTE)});
    body.replaceChildren(h("p", {}, `Signed: the hub runner stops these tasks at ${pruneClock(pending.deadline)} unless an agent keeps one (rasci.py keep <task>) or changes it first.`),
      h("div", {class: "prune-wait"}, pruneView.dial.root),
      h("ul", {class: "prune-list", "aria-label": "Signed tasks"}, pending.tasks.map((task) => h("li", {"data-task": task}, h("code", {class: "task-id"}, task)))));
  }

  function drawPrune(body) {
    const pending = Prune.pending(state.jobs || [], pruneNow());
    if (pending) {
      pruneCountdown(body, pending);
      return;
    }
    const range = Prune.MINUTES;
    pruneView.dial = dial({value: range.value, label: "Answer window in minutes", name: "prune-dial", min: range.min, max: range.max, page: range.page,
      readout: (minutes) => Dial.countdown(minutes * Prune.MINUTE), spoken: (minutes) => `${minutes} minutes for the agents to keep a task`, readonly: false, live: null});
    const count = h("span", {class: "count"}, "0");
    const go = h("button", {type: "button", class: "btn primary", id: "prune-sign", ...named("Prune", "Prune: one passkey signs the ticked tasks the filter shows and the deadline; the hub sends a Sécurité to all at once")}, icon("bi-scissors"), "Prune", count);
    go.addEventListener("click", () => signPrune(body));
    const dom = {groups: h("div", {class: "prune-groups", role: "group", "aria-label": "Stale tasks"}), rows: [], none: null, count, go};
    const filter = h("input", {class: "field prune-filter", type: "search", id: "prune-filter", value: pruneView.filter, placeholder: "Filter tasks", "aria-label": "Filter the stale tasks", on: {input: (event) => {
      pruneView.filter = event.target.value;
      pruneSync(dom);
    }}});
    body.replaceChildren(h("div", {class: "prune-tools"}, pruneStepper(dom), filter), dom.groups,
      h("div", {class: "prune-foot"}, h("div", {class: "prune-wait"}, pruneView.dial.root, h("p", {class: "muted"}, "Answer window: the agents keep a task until then; every other ticked task is set stopped.")),
        h("div", {class: "actions"}, go)));
    pruneView.ticked = new Set(pruneStale().map((row) => row.task));
    pruneRender(dom);
  }

  function openPrune() {
    Object.assign(pruneView, {days: Prune.STALE_DAYS, filter: "", collapsed: new Set()});
    const body = h("div", {class: "stack prune-dialog"});
    openSheet("Prune stale tasks", body, false);
    drawPrune(body);
  }
