  const SCHEDULE_ROWS = {
    coach: ["Coach reminder", "A one-line health tip at the top of an agent's answer, once across all agents; every N hours."],
    dream: ["Dream reminder", "A /kvb-dream hint, once per agent session; every N hours."],
    "dream-popup": ["Dream popup", "A GNOME notification to run /kvb-dream; daily times like 17:00, 21:30 or an OnCalendar expression."],
    "queue-cleanup": ["Queue cleanup", "Deletes the queue jobs no living process holds; daily times or an OnCalendar expression."],
    "code-graph": ["Code graph", "Keeps the codebase-memory-mcp daemon watching every graph; on or off only."],
  };
  const SCHEDULE_UNITS = {"dream-popup": "kvb-dream-notify.timer", "queue-cleanup": "kvb-org-queue-cleanup.timer", "code-graph": "kvb-code-graph.service"};
  const SCHEDULE_SOURCES = [["skills", "Skills"], ["hub", "Hub"], ["claude", "Claude"], ["system", "System"]];
  const SCHEDULE_CLOCK = /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/;
  const SCHEDULE_START = "systemctl --user start kvb-schedules.service";
  const SCHEDULE_HINTS = {
    hours: "Click to edit: whole hours from 1 to 24; Enter saves.",
    timer: "Click to edit: daily times like 17:00, 21:30 or a raw OnCalendar expression, which the reconciler checks with systemd-analyze; Enter saves.",
    cron: "Click to edit: a 5-field cron like 0 9 * * 1-5; Enter saves with the passkey.",
  };
  const scheduleShown = new Set(SCHEDULE_SOURCES.map(([id]) => id));

  const scheduleHost = (unit) => state.schedules.host.rows.find((row) => row.unit === unit) || null;
  const scheduleText = (row) => (Object.hasOwn(row, "every") ? `${row.every} h` : Object.hasOwn(row, "at") ? row.at.join(", ") : row.calendar || "");
  const scheduleOverride = (row) => (Object.hasOwn(row, "at") ? {at: row.at} : Object.hasOwn(row, "calendar") ? {calendar: row.calendar} : {});

  /**
   * @param {string} text what the operator typed into a timer's schedule field.
   * @returns {Object} {at} for daily times, else {calendar} with the raw OnCalendar expression.
   */
  function scheduleTiming(text) {
    const times = text.split(",").map((part) => part.trim()).filter(Boolean);
    return times.length && times.every((time) => SCHEDULE_CLOCK.test(time)) ? {at: times} : {calendar: text.trim()};
  }

  async function saveSchedule(body) {
    const result = await sendJson("/api/schedules", body);
    if (!result.ok) {
      toast("Schedule not changed", fail(result), false);
    }
    await load();
  }

  /**
   * @param {string[]} argv the schedules.py arguments of one System timer or Claude task change.
   * @param {string} label what the passkey prompt and the toast name.
   */
  async function signSchedule(argv, label) {
    const items = [{kind: "schedule", argv}];
    const signed = await proofFor(items, label);
    if (signed === null) {
      return;
    }
    const result = await sendJson("/api/schedules", {items, proof: signed.proof});
    toast(result.ok ? `Schedule: ${label}` : `Schedule: ${label}: not changed`, result.ok ? ["→ runner"] : fail(result), result.ok);
    await load();
  }

  /**
   * @param {string} name a key of SCHEDULE_ROWS.
   * @returns {Object} its table row: the stored row of schedules.json, the runs of its unit and how it saves.
   */
  function skillsRow(name) {
    const row = state.schedules.rows[name];
    const host = SCHEDULE_UNITS[name] ? scheduleHost(SCHEDULE_UNITS[name]) : null;
    const save = (value) => saveSchedule({row: name, value});
    const input = Object.hasOwn(row, "every") ? "hours" : Object.keys(scheduleOverride(row)).length ? "timer" : null;
    return {key: name, source: "skills", name: SCHEDULE_ROWS[name][0], hint: SCHEDULE_ROWS[name][1], schedule: scheduleText(row), input, host, on: row.on, reset: null,
      toggle: (on) => save({...row, on}),
      edit: (text) => save(input === "hours" ? {on: row.on, every: Number(text.replace(/\s*h$/, ""))} : {on: row.on, ...scheduleTiming(text)})};
  }

  /**
   * @param {Object} host a hub timer of the host view.
   * @returns {Object} its table row; its override in schedules.json, if any, wins over what the host last saw.
   */
  function hubRow(host) {
    const override = state.schedules.units[host.unit] || null;
    const timing = override ? scheduleOverride(override) : {};
    const on = override ? override.on : host.on;
    const save = (value) => saveSchedule({unit: host.unit, value});
    return {key: host.unit, source: "hub", name: host.name, hint: host.file, schedule: Object.keys(timing).length ? scheduleText(timing) : host.schedule, input: "timer", host, on,
      reset: host.dropin || Object.keys(timing).length ? () => save({on}) : null,
      toggle: (value) => save({on: value, ...timing}), edit: (text) => save({on, ...scheduleTiming(text)})};
  }

  /**
   * @param {Object} host a System timer of the host view.
   * @returns {Object} its table row; every change is signed with the passkey and runs through the host runner.
   */
  function systemRow(host) {
    const sign = (rest, label) => signSchedule(["timer", host.unit, ...rest], `${label} ${host.unit}`);
    return {key: host.unit, source: "system", name: host.name, hint: host.file, schedule: host.schedule, input: "timer", host, on: host.on,
      reset: host.dropin ? () => sign(["--reset"], "Reset") : null,
      toggle: (on) => sign([on ? "--on" : "--off"], on ? "Switch on" : "Switch off"),
      edit: (text) => {
        const timing = scheduleTiming(text);
        sign(timing.at ? ["--at", ...timing.at] : ["--calendar", timing.calendar], "Retime");
      }};
  }

  /**
   * @param {Object} host a Claude task of the host view.
   * @returns {Object} its table row; switching it off removes the task from its scheduled_tasks.json, signed with the passkey.
   */
  function claudeRow(host) {
    const sign = (rest, label) => signSchedule(["cron", host.file, host.task, ...rest], `${label} ${host.name}`);
    return {key: `${host.file}#${host.task}`, source: "claude", name: host.name, hint: host.command || host.file, schedule: host.schedule, input: "cron", host, on: true, reset: null,
      toggle: (on) => (on ? null : sign(["--remove"], "Remove")), edit: (text) => sign(["--cron", text.trim()], "Retime")};
  }

  function scheduleRows() {
    const others = state.schedules.host.rows;
    const of = (source, build) => others.filter((row) => row.source === source).map(build);
    return [...Object.keys(SCHEDULE_ROWS).map(skillsRow), ...of("hub", hubRow), ...of("claude", claudeRow), ...of("system", systemRow)];
  }

  /**
   * @param {HTMLElement} cell the schedule cell of a row.
   * @param {Object} row the table row, with its schedule and edit().
   */
  function scheduleField(cell, row) {
    const field = h("input", {class: "field sched-input", type: "text", value: row.schedule, "aria-label": `${row.name}: schedule`, title: SCHEDULE_HINTS[row.input],
      on: {keydown: (event) => {
        if (event.key === "Enter" && field.value.trim()) {
          event.preventDefault();
          row.edit(field.value);
        } else if (event.key === "Escape") {
          cell.replaceChildren(scheduleCellText(row));
        }
      }}});
    cell.replaceChildren(field);
    field.focus();
  }

  /**
   * @param {Object} row a table row.
   * @returns {HTMLElement} its schedule as text.
   */
  function scheduleCellText(row) {
    return h("code", {}, dash(row.schedule));
  }

  /**
   * @param {Object} row a table row.
   * @returns {HTMLElement} its schedule cell; a click turns it into a field when the row takes a schedule.
   */
  function scheduleCell(row) {
    const cell = h("td", {class: "sched-cell", "data-edit": row.input || "", title: row.input ? SCHEDULE_HINTS[row.input] : "on or off only"});
    cell.append(scheduleCellText(row));
    if (row.input) {
      cell.addEventListener("click", () => cell.querySelector("input") || scheduleField(cell, row));
    }
    return cell;
  }

  /**
   * @param {Object} row a table row.
   * @returns {HTMLElement} its line: source, name with its error, schedule, next and last run, the switch and a Reset where a drop-in exists.
   */
  function scheduleLine(row) {
    const host = row.host;
    const error = host && host.error ? h("span", {class: "pill", "data-tone": "bad", title: host.error}, "error") : null;
    const toggle = h("input", {type: "checkbox", role: "switch", checked: row.on, disabled: row.source === "claude" && !row.on, "aria-label": `${row.name}: on`,
      title: row.source === "claude" ? "Off removes the task, signed with the passkey" : row.source === "system" ? "Signed with the passkey" : null,
      on: {change: (event) => row.toggle(event.target.checked)}});
    const reset = row.reset ? h("button", {type: "button", class: "btn small ghost", "data-reset": "", ...named(`Reset ${row.name}`, "Reset: remove the schedule.conf drop-in, keep the unit file"), on: {click: row.reset}}, "Reset") : null;
    return h("tr", {class: row.on ? null : "off", "data-schedule": row.key, "data-source": row.source},
      h("td", {}, pill(row.source, row.source === "skills" || row.source === "hub" ? "ok" : "warn")), h("th", {scope: "row", title: row.hint}, row.name, error),
      scheduleCell(row), h("td", {}, host && host.next !== null ? when(host.next) : "–"), h("td", {}, host && host.last !== null ? when(host.last) : "–"),
      h("td", {class: "sched-on"}, toggle, reset));
  }

  function scheduleChips(redraw) {
    return h("div", {class: "chips", role: "group", "aria-label": "Show sources"}, SCHEDULE_SOURCES.map(([id, label]) => h("button", {type: "button", class: "chip", "data-source-chip": id, "aria-pressed": String(scheduleShown.has(id)), on: {click: () => {
      if (scheduleShown.has(id)) {
        scheduleShown.delete(id);
      } else {
        scheduleShown.add(id);
      }
      redraw();
    }}}, label)));
  }

  function scheduleTable() {
    const rows = scheduleRows().filter((row) => scheduleShown.has(row.source));
    return h("div", {class: "fw-table-wrap"}, h("table", {class: "fw-table sched-table", "aria-label": "Schedules"},
      h("thead", {}, h("tr", {}, ["Source", "Name", "Schedule", "Next", "Last", "On"].map((cell) => h("th", {scope: "col"}, cell)))),
      h("tbody", {}, rows.map(scheduleLine))));
  }

  /**
   * @returns {HTMLElement} the Schedules panel: the reconciler's last run once in the header, one chip per source and one table of
   * every first-party row, hub timer, Claude task and System timer.
   */
  function schedulesContent() {
    const box = h("div", {class: "stack sched"});
    const draw = () => {
      const at = state.schedules.host.at;
      const head = at === null
        ? h("p", {class: "muted"}, "The host has not listed its timers and tasks yet: ", h("code", {}, SCHEDULE_START), copyButton(SCHEDULE_START))
        : h("p", {class: "muted sched-head"}, "Reconciler ran ", when(at));
      box.replaceChildren(h("div", {class: "row sched-bar"}, scheduleChips(draw), head), scheduleTable());
    };
    draw();
    return box;
  }

  function schedulesPanel() {
    return h("section", {class: "card", "data-panel": "stream/schedules", "aria-label": "Schedules"}, schedulesContent());
  }
