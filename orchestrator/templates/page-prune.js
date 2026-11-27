  const PRUNE_TICK = 1000;
  const pruneView = {days: Prune.STALE_DAYS, ticked: new Set(), dial: null, body: null, timer: null};

  const pruneNow = () => Date.now() / 1000;
  const pruneClock = (epoch) => new Date(epoch * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  const pruneStale = () => Prune.stale(state.tasks, markSources(), pruneView.days);

  function pruneTick() {
    const pending = Prune.pending(state.jobs || [], pruneNow());
    const chip = document.getElementById("kanban-prune");
    if (chip && pending) {
      chip.querySelector(".prune-left").textContent = Prune.clock(pending.left);
    }
    const body = pruneView.body;
    if (body && body.isConnected && pending && pruneView.dial && pruneView.dial.root.getAttribute("aria-readonly") === "true") {
      pruneView.dial.set(Math.ceil(pending.left / Prune.MINUTE));
      body.querySelector(".prune-left").textContent = Prune.clock(pending.left);
    }
    if (!pending && !(body && body.isConnected)) {
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
   * @returns {HTMLElement[]} the Prune button, which opens the prune dialog, and while a signed prune waits for its
   * deadline the countdown chip naming its tasks and deadline.
   */
  function pruneControls(stale) {
    const pending = Prune.pending(state.jobs || [], pruneNow());
    const open = h("button", {type: "button", class: "btn small", id: "kanban-prune-open", disabled: !stale && !pending, ...named("Prune", "Prune stale tasks: one passkey signs the list and a deadline; the agents can keep a task until then")}, icon("bi-scissors"), "Prune");
    open.addEventListener("click", openPrune);
    if (!pending) {
      return [open];
    }
    pruneTicking();
    const words = `Prune at ${pruneClock(pending.deadline)}: ${pending.tasks.join(", ")}`;
    const chip = h("span", {class: "pill prune-chip", id: "kanban-prune", "data-tone": "warn", "data-deadline": String(pending.deadline), role: "timer", ...named(`Prune in ${Prune.clock(pending.left)}`, words)},
      icon("bi-hourglass-split"), h("span", {class: "prune-left"}, Prune.clock(pending.left)));
    return [open, chip];
  }

  function pruneRows(list, count) {
    const rows = pruneStale();
    pruneView.ticked = new Set([...pruneView.ticked].filter((task) => rows.some((row) => row.task === task)));
    count.textContent = String(pruneView.ticked.size);
    list.replaceChildren(...(rows.length ? rows.map((row) => h("li", {"data-task": row.task}, h("label", {class: "check"},
      h("input", {type: "checkbox", checked: pruneView.ticked.has(row.task), "aria-label": `Prune ${row.task}`, on: {change: (event) => {
        if (event.target.checked) {
          pruneView.ticked.add(row.task);
        } else {
          pruneView.ticked.delete(row.task);
        }
        count.textContent = String(pruneView.ticked.size);
        count.closest("button").disabled = !pruneView.ticked.size;
      }}}), h("code", {class: "task-id"}, row.task), h("span", {class: "muted"}, `${Math.floor((state.now - row.updated) / 86400)} d`))))
      : [h("li", {class: "muted"}, `No task without a register change for ${pruneView.days} days.`)]));
    count.closest("button").disabled = !pruneView.ticked.size;
  }

  function retick(list, count) {
    pruneView.ticked = new Set(pruneStale().map((row) => row.task));
    pruneRows(list, count);
  }

  async function signPrune(body) {
    const tasks = pruneStale().map((row) => row.task).filter((task) => pruneView.ticked.has(task));
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
      unit: "min", spoken: (minutes) => `${minutes} minutes until the prune`, readonly: true});
    pruneTicking();
    body.replaceChildren(h("p", {}, `Signed: the hub runner stops these tasks at ${pruneClock(pending.deadline)} unless an agent keeps one (rasci.py keep <task>) or changes it first.`),
      h("div", {class: "prune-wait"}, pruneView.dial.root, h("strong", {class: "prune-left", role: "timer"}, Prune.clock(pending.left))),
      h("ul", {class: "prune-list", "aria-label": "Signed tasks"}, pending.tasks.map((task) => h("li", {"data-task": task}, h("code", {class: "task-id"}, task)))));
  }

  function drawPrune(body) {
    pruneView.body = body;
    const pending = Prune.pending(state.jobs || [], pruneNow());
    if (pending) {
      pruneCountdown(body, pending);
      return;
    }
    const range = Prune.MINUTES;
    pruneView.dial = dial({value: range.value, label: "Answer window in minutes", name: "prune-dial", min: range.min, max: range.max, page: range.page, unit: "min",
      spoken: (minutes) => `${minutes} minutes for the agents to keep a task`, readonly: false});
    const count = h("span", {class: "count"}, "0");
    const go = h("button", {type: "button", class: "btn primary", id: "prune-sign", ...named("Prune", "Prune: one passkey signs the ticked tasks and the deadline; the hub sends a Sécurité to all at once")}, icon("bi-scissors"), "Prune", count);
    go.addEventListener("click", () => signPrune(body));
    const list = h("ul", {class: "prune-list", "aria-label": "Stale tasks"});
    const field = h("input", {class: "field", type: "text", inputmode: "numeric", id: "prune-days", value: String(pruneView.days), "aria-label": "Days without a register change", on: {change: (event) => {
      const days = Prune.daysOf(event.target.value);
      event.target.setAttribute("aria-invalid", String(days === null));
      if (days !== null) {
        pruneView.days = days;
        retick(list, count);
      }
    }}});
    body.replaceChildren(h("label", {class: "prune-days"}, h("span", {class: "muted"}, "Stale after days"), field), list,
      h("div", {class: "prune-wait"}, pruneView.dial.root, h("p", {class: "muted"}, "Answer window: the agents keep a task until then; every other ticked task is set stopped.")),
      h("div", {class: "actions"}, go));
    retick(list, count);
  }

  function openPrune() {
    pruneView.days = Prune.STALE_DAYS;
    const body = h("div", {class: "stack prune-dialog"});
    openSheet("Prune stale tasks", body, false);
    drawPrune(body);
  }
