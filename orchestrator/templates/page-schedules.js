  const SCHEDULE_ROWS = {
    coach: ["Coach reminder", "bi-heart-pulse", "A one-line health tip at the top of an agent's answer, once across all agents."],
    dream: ["Dream reminder", "bi-moon-stars", "A /kvb-dream hint, once per agent session."],
    "dream-popup": ["Dream popup", "bi-bell", "A GNOME notification to run /kvb-dream."],
    "queue-cleanup": ["Queue cleanup", "bi-trash3", "Deletes the queue jobs no living process holds."],
    "code-graph": ["Code graph", "bi-diagram-3", "Keeps the codebase-memory-mcp daemon watching every graph."],
  };
  const SCHEDULE_UNITS = {"dream-popup": "kvb-dream-notify.timer", "queue-cleanup": "kvb-org-queue-cleanup.timer", "code-graph": "kvb-code-graph.service"};
  const SCHEDULE_HOURS = [1, 24];
  const SCHEDULE_START = "systemctl --user start kvb-schedules.service";

  async function saveSchedule(name, value) {
    const result = await sendJson("/api/schedules", {row: name, value});
    if (result.ok && result.data) {
      state.schedules = result.data;
    } else {
      toast("Schedule not changed", fail(result), false);
    }
    await load();
  }

  const scheduleHost = (unit) => state.schedules.host.rows.find((row) => row.unit === unit) || null;
  const scheduleTimes = (text) => text.split(",").map((part) => part.trim()).filter(Boolean);

  /**
   * @param {Object} host a row of the host view, or null.
   * @returns {HTMLElement} its next and last run, or why there is none yet.
   */
  function scheduleRuns(host) {
    if (!host || (host.next === null && host.last === null)) {
      return h("span", {class: "muted"}, "no run known");
    }
    return h("span", {class: "muted sched-runs"}, host.next === null ? null : ["next ", when(host.next)], host.next !== null && host.last !== null ? " · " : null, host.last === null ? null : ["last ", when(host.last)]);
  }

  /**
   * @param {string} name a key of SCHEDULE_ROWS.
   * @param {Object} row its stored row: on, plus every or at.
   * @returns {HTMLElement} the row: switch, its timing field and its runs.
   */
  function scheduleRow(name, row) {
    const [label, glyph, hint] = SCHEDULE_ROWS[name];
    const change = (key, value) => saveSchedule(name, {...state.schedules.rows[name], [key]: value});
    const toggle = h("input", {type: "checkbox", role: "switch", checked: row.on, "aria-label": `${label}: on`, on: {change: (event) => change("on", event.target.checked)}});
    const timing = [];
    if (Object.hasOwn(row, "every")) {
      timing.push(h("label", {class: "sched-field"}, "every", h("input", {class: "field sched-hours", type: "number", min: SCHEDULE_HOURS[0], max: SCHEDULE_HOURS[1], step: 1, value: row.every, "aria-label": `${label}: every hours`,
        on: {change: (event) => change("every", Number(event.target.value))}}), "h"));
    }
    if (Object.hasOwn(row, "at")) {
      timing.push(h("label", {class: "sched-field"}, "at", h("input", {class: "field sched-times", type: "text", value: row.at.join(", "), placeholder: "17:00, 21:30", "aria-label": `${label}: at times`,
        on: {change: (event) => change("at", scheduleTimes(event.target.value))}})));
    }
    const unit = SCHEDULE_UNITS[name];
    return h("li", {class: `sched-row${row.on ? "" : " off"}`, "data-schedule": name},
      h("label", {class: "sched-switch"}, toggle, icon(glyph), h("span", {class: "sched-name"}, label)),
      h("span", {class: "sched-hint muted"}, hint), ...timing, unit ? scheduleRuns(scheduleHost(unit)) : null);
  }

  /**
   * @param {Object} host a host view row the hub must not switch: a hub unit or a foreign timer or hook.
   * @returns {HTMLElement} its schedule, runs and, for a foreign row, its off command to copy.
   */
  function scheduleForeign(host) {
    return h("li", {class: "sched-row foreign", "data-schedule-foreign": host.name},
      h("span", {class: "sched-name"}, host.name), h("span", {class: `chip ${host.owner === "hub" ? "ok" : ""}`}, host.owner),
      h("code", {class: "sched-hint"}, host.kind === "hook" ? host.command : dash(host.schedule)), host.kind === "hook" ? null : scheduleRuns(host),
      host.off ? h("span", {class: "sched-off"}, h("code", {}, host.off), host.kind === "hook" ? null : copyButton(host.off)) : null);
  }

  /**
   * @returns {HTMLElement} the Schedules panel: the first-party rows, then every other timer and hook the host
   * reconciler last saw; a hint with its start command before its first run.
   */
  function schedulesContent() {
    const {rows, host} = state.schedules;
    const others = host.rows.filter((row) => row.owner !== "skills");
    return h("div", {class: "stack sched"},
      h("ul", {class: "sched-list", "aria-label": "Switchable"}, Object.keys(SCHEDULE_ROWS).map((name) => scheduleRow(name, rows[name]))),
      host.at === null
        ? h("p", {class: "muted"}, "The host has not listed its timers and hooks yet: ", h("code", {}, SCHEDULE_START), copyButton(SCHEDULE_START))
        : h("div", {}, h("h3", {}, "Other timers and hooks"), h("p", {class: "muted"}, "Seen ", when(host.at), "; the hub never switches these."),
          h("ul", {class: "sched-list", "aria-label": "Read only"}, others.map(scheduleForeign))));
  }

  function schedulesPanel() {
    return h("section", {class: "card", "data-panel": "stream/schedules", "aria-label": "Schedules"}, schedulesContent());
  }
