  const LIMIT_PROFILES = [["calm", "Calm"], ["balanced", "Balanced"], ["max", "Max"]];
  const LIMIT_DIAL = {min: 0, max: 100, page: 5};
  const LIMIT_LABEL = {gap: 3, inset: 4, step: 64};
  const limitView = {data: null, busy: false, metric: "cpu", dom: null};

  const limitsHeld = () => (limitView.data ? limitView.data.limits || limitView.data.profiles.balanced : null);

  async function fetchLimits() {
    if (limitView.busy) {
      return;
    }
    limitView.busy = true;
    try {
      const response = await fetch("/api/limits", {cache: "no-store"});
      if (response.ok) {
        limitView.data = await response.json();
      }
    } catch {
      ui.offline = true;
    }
    limitView.busy = false;
    drawResources();
  }

  /**
   * @returns {HTMLElement} the row above the Hardware chart: the profile switch, which metric's limit lines the chart
   * draws, and the Limits button that opens the table of every value.
   */
  function limitBar() {
    const profiles = LIMIT_PROFILES.map(([id, label]) => [id, label, h("button", {type: "button", "data-profile": id, "aria-pressed": "false", on: {click: () => chooseProfile(id, label)}}, label)]);
    const metrics = Limits.METRICS.map((metric) => [metric, h("button", {
      type: "button", "data-metric": metric, "aria-pressed": String(metric === limitView.metric), title: `Limit lines of ${Limits.NAMES[metric]}`, on: {click: () => {
        limitView.metric = metric;
        drawResources();
      }},
    }, Limits.NAMES[metric])]);
    const sheet = h("button", {type: "button", class: "btn small soft", id: "limits-open", ...named("Limits", "Limits: every lower, upper, STOP and MAYDAY value in one table, each with its dial"), on: {click: openLimits}},
      icon("bi-sliders"), h("span", {}, "Limits"));
    const note = h("span", {class: "muted limit-note"});
    limitView.dom = {profiles, metrics, sheet, note};
    return h("div", {class: "res-limits"},
      h("div", {class: "segmented limit-profiles", role: "group", "aria-label": "Profile"}, profiles.map((entry) => entry[2])),
      h("div", {class: "segmented limit-metrics", role: "group", "aria-label": "Limit lines"}, metrics.map((entry) => entry[1])), sheet, note);
  }

  function drawLimitBar() {
    const dom = limitView.dom;
    if (!dom) {
      return;
    }
    const data = limitView.data;
    const chosen = data ? Limits.profileOf(data.limits, data.profiles) : null;
    for (const [id, label, button] of dom.profiles) {
      const values = data && data.profiles ? data.profiles[id] : null;
      button.setAttribute("aria-pressed", String(id === chosen));
      button.disabled = !values;
      button.title = values ? `${label}: band ${values.cpu.lower} to ${values.cpu.upper} %; sets every limit at once` : "The limits are not loaded";
    }
    for (const [metric, button] of dom.metrics) {
      button.setAttribute("aria-pressed", String(metric === limitView.metric));
    }
    dom.sheet.disabled = !data;
    dom.note.textContent = !data ? "" : data.why ? revealed(data.why) : data.limits ? "" : "No limits.json: the queue config applies";
  }

  /**
   * @param {Object} frame the chart frame of resourceFrame().
   * @param {Function} y maps a percent to the chart's y.
   */
  function limitLines(frame, y) {
    const data = limitView.data;
    if (!data || !data.limits) {
      return;
    }
    const metric = limitView.metric;
    const name = Limits.NAMES[metric];
    const target = Limits.TARGETED.includes(metric) && data.target ? data.target[metric] : null;
    if (typeof target === "number") {
      const at = fixed(y(target));
      frame.svg.append(s("g", {class: "res-target", "data-metric": metric, "data-value": String(target)}, s("title", {}, `${name} target ${target.toFixed(1)} %: the live target the queue admits up to`),
        s("line", {x1: RESOURCE.left, x2: fixed(frame.right), y1: at, y2: at}), s("text", {x: RESOURCE.left + LIMIT_LABEL.inset, y: fixed(y(target) - LIMIT_LABEL.gap)}, `target ${Math.round(target)}`)));
    }
    Limits.LEVELS.forEach((level, index) => {
      const value = data.limits[metric][level];
      const words = `${name} ${Limits.LEVEL_NAMES[level]} ${value} %`;
      const at = fixed(y(value));
      const open = () => limitDial(metric, level, null);
      const press = (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      };
      frame.svg.append(s("g", {class: `res-limit ${level}`, "data-metric": metric, "data-level": level, "data-value": String(value), role: "button", tabindex: 0, "aria-label": words, on: {click: open, keydown: press}},
        s("title", {}, `${words}: click to set it on a dial`),
        s("line", {class: "res-limit-hit", x1: RESOURCE.left, x2: fixed(frame.right), y1: at, y2: at}),
        s("line", {class: "res-limit-mark", x1: RESOURCE.left, x2: fixed(frame.right), y1: at, y2: at}),
        s("text", {x: fixed(frame.right - LIMIT_LABEL.inset - index * LIMIT_LABEL.step), y: fixed(y(value) - LIMIT_LABEL.gap), "text-anchor": "end"}, `${Limits.LEVEL_NAMES[level]} ${value}`)));
    });
  }

  /**
   * @param {Object} next valid limits to save.
   * @param {string} label what the passkey prompt and the toast name.
   * @returns {Promise<boolean>} whether the hub saved them: a value that stays or tightens saves at once, a looser one
   * only once the passkey signs it; a canceled passkey sends nothing and keeps the old values.
   */
  async function saveLimits(next, label) {
    const held = limitView.data.limits;
    const loose = Limits.loosened(next, held);
    const words = !loose.length ? label : held ? `${label}: loosens ${loose.map(Limits.said).join(", ")}` : `${label}: the first limits.json`;
    const signed = await signedProof("/api/limits/sign", {limits: next}, words);
    if (signed === null) {
      return false;
    }
    const result = await sendJson("/api/limits", {limits: next, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast(`${label}: not saved`, fail(result), false);
      return false;
    }
    limitView.data = result.data;
    toast(label, [loose.length ? "Signed and saved to limits.json" : "Saved to limits.json"], true);
    drawResources();
    return true;
  }

  async function chooseProfile(id, label) {
    const data = limitView.data;
    if (data && Limits.profileOf(data.limits, data.profiles) !== id) {
      await saveLimits(data.profiles[id], `Profile ${label}`);
    }
  }

  /**
   * @param {string} metric one of Limits.METRICS.
   * @param {string} level one of Limits.LEVELS.
   * @param {Function|null} back what Cancel and a save return to: the Limits sheet, or null to close.
   */
  function limitDial(metric, level, back) {
    const held = limitsHeld();
    if (!held) {
      return;
    }
    const title = `${Limits.NAMES[metric]} ${Limits.LEVEL_NAMES[level]}`;
    const picked = dial({value: held[metric][level], label: `${title} in percent`, name: "limit-dial", ...LIMIT_DIAL, unit: "%", spoken: (value) => `${title} ${value} %`, readonly: false});
    const error = h("p", {class: "limit-error", role: "alert", hidden: true});
    const leave = back || closeSheet;
    const save = async () => {
      const value = picked.value();
      const why = Limits.problem(Limits.withValue(held, metric, level, value));
      error.hidden = why === null;
      error.textContent = why || "";
      if (why === null && await saveLimits(Limits.withValue(held, metric, level, value), `${title} ${value} %`)) {
        leave();
      }
    };
    openSheet(title, h("div", {class: "stack limit-sheet", "data-metric": metric, "data-level": level},
      h("p", {class: "muted"}, `${Limits.ORDER} per metric. A lower value applies at once; a higher one admits more load or raises an alarm threshold, so the passkey signs it.`),
      picked.root, error,
      h("div", {class: "sheet-foot"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost limit-cancel", leave), btn("Save", "btn primary limit-save", save))), false);
    picked.root.focus({preventScroll: true});
  }

  function openLimits() {
    const data = limitView.data;
    const held = limitsHeld();
    if (!held) {
      return;
    }
    const cell = (metric, level) => {
      const words = `${Limits.NAMES[metric]} ${Limits.LEVEL_NAMES[level]} ${held[metric][level]} %`;
      return h("td", {}, h("button", {type: "button", class: "btn small soft limit-cell", "data-metric": metric, "data-level": level, ...named(words, `${words}: open its dial`), on: {click: () => limitDial(metric, level, openLimits)}},
        `${held[metric][level]} %`));
    };
    openSheet("Limits", h("div", {class: "stack limits-sheet"},
      h("p", {class: "muted"}, data.limits ? `limits.json in the council directory, ${Limits.ORDER} per metric; a click on a value opens its dial.` : "No limits.json yet, so the queue config applies: the table shows Balanced, and the first save needs the passkey."),
      data.why ? h("p", {class: "limit-error", role: "alert"}, revealed(data.why)) : null,
      h("div", {class: "table-wrap"}, h("table", {class: "limits-table", "aria-label": "Limits"},
        h("thead", {}, h("tr", {}, h("th", {scope: "col"}, "Metric"), Limits.LEVELS.map((level) => h("th", {scope: "col"}, Limits.LEVEL_NAMES[level])))),
        h("tbody", {}, Limits.METRICS.map((metric) => h("tr", {"data-metric": metric}, h("th", {scope: "row"}, Limits.NAMES[metric]), Limits.LEVELS.map((level) => cell(metric, level)))))))), false);
  }
