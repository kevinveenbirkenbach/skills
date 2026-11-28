  const LIMIT_PROFILES = [["calm", "Calm"], ["balanced", "Balanced"], ["max", "Max"]];
  const LIMIT_LABEL = {gap: 3, inset: 4, step: 64};
  const LIMIT_STEPS = {ArrowUp: 1, ArrowDown: -1, PageUp: 5, PageDown: -5};
  const LIMIT_SHOWN_KEY = "kvb-orchestrator.limit-levels";
  const limitView = {data: null, busy: false, metric: "cpu", dom: null, staged: {}, drag: null, saving: false, shown: null, sheet: null, cells: []};

  const limitsHeld = () => (limitView.data ? limitView.data.limits || limitView.data.profiles.balanced : null);
  const limitShownOf = (value) => Object.fromEntries(Limits.SHOWN.map((level) => [level, !(value && value[level] === false)]));
  const limitShown = () => limitView.shown || limitShownOf(null);

  /**
   * @returns {Object|null} Limits.review() of the staged values against the limits the lines show, null while the
   * limits are not loaded.
   */
  function limitReview() {
    const base = limitsHeld();
    return base ? Limits.review(base, limitView.data.limits, limitView.staged) : null;
  }

  function limitValue(metric, level) {
    const key = `${metric}.${level}`;
    return Object.hasOwn(limitView.staged, key) ? limitView.staged[key] : limitsHeld()[metric][level];
  }

  /**
   * @param {string} metric one of Limits.METRICS.
   * @param {string} level one of Limits.LEVELS.
   * @param {number} value the value to stage; the value the lines show unstages it.
   */
  function stageLimit(metric, level, value) {
    const base = limitsHeld();
    const key = `${metric}.${level}`;
    if (!base) {
      return;
    }
    if (value === base[metric][level]) {
      delete limitView.staged[key];
    } else {
      limitView.staged[key] = value;
    }
  }

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
   * @returns {Object} the bar of staged lines: {root, note, error, save, discard}; Save sends every staged value in one
   * request, Discard drops them all.
   */
  function limitStageBar() {
    const note = h("span", {class: "muted limit-stage-note"});
    const error = h("span", {class: "limit-error", role: "alert", hidden: true});
    const discard = h("button", {type: "button", class: "btn small ghost limit-discard", title: "Discard: drop every staged value, the lines return to the limits in force", on: {click: discardStaged}}, "Discard");
    const save = h("button", {type: "button", class: "btn small primary limit-save", on: {click: saveStaged}}, "Save");
    return {root: h("div", {class: "limit-stage", role: "group", "aria-label": "Staged limits", hidden: true}, note, error, discard, save), note, error, save, discard};
  }

  /**
   * @returns {HTMLElement} the row above the Hardware chart: the Limits menu (a checkbox per level, the profiles and
   * the matrix), which metric's limit lines the chart draws, a note on the limits file and the bar of staged lines.
   */
  function limitBar() {
    limitView.shown = limitShownOf(stored(LIMIT_SHOWN_KEY, null));
    const levels = Limits.SHOWN.map((level) => {
      const box = h("input", {type: "checkbox", "data-level": level, "aria-label": `${Limits.SHOWN_NAMES[level]} lines`, on: {change: () => showLevel(level, box.checked)}});
      return {level, box, row: h("label", {class: "menu-item res-pick limit-level", title: Limits.meaning(level)}, box, h("span", {class: `limit-swatch ${level}`, "aria-hidden": "true"}), h("span", {}, Limits.SHOWN_NAMES[level]))};
    });
    const profiles = LIMIT_PROFILES.map(([id, label]) => [id, label, h("button", {type: "button", "data-profile": id, "aria-pressed": "false", on: {click: () => chooseProfile(id, label)}}, label)]);
    const matrix = h("button", {type: "button", class: "btn small soft limit-matrix", id: "limits-open", ...named("Matrix…", "Matrix: every lower, upper, STOP and MAYDAY value of every metric in one table; a right click on the chart opens it too"), on: {click: openLimits}}, icon("bi-table"), h("span", {}, "Matrix…"));
    const menu = h("details", {class: "menu res-limits-menu"}, h("summary", {...named("Limits", "Limits: show or hide the lines of each level, pick a profile, or open the matrix of every value")}, icon("bi-sliders"), h("span", {}, "Limits"), caret()),
      h("div", {class: "menu-box", role: "group", "aria-label": "Limits"},
        h("h3", {}, "Lines"), levels.map((entry) => entry.row),
        h("h3", {}, "Profile"), h("div", {class: "segmented limit-profiles", role: "group", "aria-label": "Profile"}, profiles.map((entry) => entry[2])), matrix));
    const metrics = Limits.METRICS.map((metric) => [metric, h("button", {
      type: "button", "data-metric": metric, "aria-pressed": String(metric === limitView.metric), title: `Limit lines of ${Limits.NAMES[metric]}`, on: {click: () => {
        limitView.metric = metric;
        drawResources();
      }},
    }, Limits.NAMES[metric])]);
    const note = h("span", {class: "muted limit-note"});
    const stage = limitStageBar();
    limitView.dom = {levels, profiles, metrics, menu, matrix, note, stage};
    return h("div", {class: "res-limits"}, menu,
      h("div", {class: "segmented limit-metrics", role: "group", "aria-label": "Limit lines"}, metrics.map((entry) => entry[1])), note, stage.root);
  }

  function showLevel(level, on) {
    limitView.shown = {...limitShown(), [level]: on};
    keep(LIMIT_SHOWN_KEY, limitView.shown);
    drawResources();
  }

  /**
   * @param {Object} bar a limitStageBar().
   * @param {Object|null} review limitReview().
   */
  function drawLimitStage(bar, review) {
    const count = review ? review.changes.length : 0;
    const broken = review ? review.broken : null;
    bar.root.hidden = count === 0 && !broken;
    bar.save.textContent = `Save ${count} change${count === 1 ? "" : "s"}`;
    bar.save.disabled = count === 0 || Boolean(broken) || limitView.saving;
    bar.discard.disabled = limitView.saving;
    bar.save.title = broken ? `Not possible: ${broken.words}` : review && review.loose.length ? "Save: one passkey signature covers every looser value of this batch" : "Save: tighter values save without the passkey";
    bar.note.textContent = review ? `${review.changes.map(Limits.said).join(", ")}${review.loose.length ? " · passkey" : ""}` : "";
    bar.error.hidden = !broken;
    bar.error.textContent = broken ? broken.words : "";
  }

  function drawLimitCells() {
    const held = limitsHeld();
    for (const input of limitView.cells) {
      const metric = input.getAttribute("data-metric");
      const level = input.getAttribute("data-level");
      const value = limitValue(metric, level);
      const moved = value !== held[metric][level];
      input.setAttribute("class", `limit-cell${moved ? " moved" : ""}`);
      input.title = `${Limits.NAMES[metric]} ${Limits.LEVEL_NAMES[level]}${moved ? ` was ${held[metric][level]} %` : ""}: ${Limits.meaning(level)}`;
      if (input !== document.activeElement) {
        input.value = Number.isFinite(value) ? String(value) : "";
      }
    }
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
      button.disabled = !values || limitView.saving;
      button.title = values ? `${label}: band ${values.cpu.lower} to ${values.cpu.upper} %; sets every limit at once` : "The limits are not loaded";
    }
    for (const [metric, button] of dom.metrics) {
      button.setAttribute("aria-pressed", String(metric === limitView.metric));
    }
    const shown = limitShown();
    for (const {level, box} of dom.levels) {
      box.checked = shown[level];
    }
    dom.matrix.disabled = !data;
    dom.note.textContent = !data ? "" : data.why ? revealed(data.why) : data.limits ? "" : "No limits.json: the queue config applies";
    const review = limitReview();
    drawLimitStage(dom.stage, review);
    if (limitView.sheet && limitView.sheet.root.isConnected) {
      drawLimitStage(limitView.sheet, review);
      drawLimitCells();
    }
  }

  /**
   * @param {SVGElement} node a limit line's group of limitLine().
   * @param {Object} frame the chart frame of resourceFrame().
   * @param {Function} y maps a percent to the chart's y.
   * Draws the line at its staged value: solid at the value in force, dashed with the new and the old value once moved.
   */
  function limitPaint(node, frame, y) {
    const metric = node.getAttribute("data-metric");
    const level = node.getAttribute("data-level");
    const held = limitView.data.limits[metric][level];
    const value = limitValue(metric, level);
    const moved = value !== held;
    const words = `${Limits.NAMES[metric]} ${Limits.LEVEL_NAMES[level]}`;
    const at = fixed(y(value));
    const label = `${Limits.LEVEL_NAMES[level]} ${value}${moved ? ` (was ${held})` : ""}`;
    node.setAttribute("class", `res-limit ${level}${moved ? " moved" : ""}`);
    node.setAttribute("data-value", String(value));
    node.setAttribute("aria-label", words);
    node.setAttribute("aria-valuenow", String(value));
    node.setAttribute("aria-valuetext", moved ? `${value} %, was ${held} %` : `${value} %`);
    const was = moved ? s("line", {class: "res-limit-was", x1: RESOURCE.left, x2: fixed(frame.right), y1: fixed(y(held)), y2: fixed(y(held))}) : null;
    const parts = [
      s("title", {}, `${words} ${value} %${moved ? ` (was ${held} %)` : ""}: ${Limits.meaning(level)}. Drag it, or focus it and press the arrow keys, to stage a new value.`),
      was,
      s("line", {class: "res-limit-hit", x1: RESOURCE.left, x2: fixed(frame.right), y1: at, y2: at}),
      s("line", {class: "res-limit-mark", x1: RESOURCE.left, x2: fixed(frame.right), y1: at, y2: at}),
      s("text", {x: fixed(frame.right - LIMIT_LABEL.inset - Limits.LEVELS.indexOf(level) * LIMIT_LABEL.step), y: fixed(y(value) - LIMIT_LABEL.gap), "text-anchor": "end"}, label),
    ];
    node.replaceChildren(...parts.filter(Boolean));
  }

  /**
   * @param {PointerEvent} event a pointer event over the chart.
   * @param {SVGSVGElement} svg the chart.
   * @returns {number} the event's y in the chart's coordinates.
   */
  function limitChartY(event, svg) {
    const box = svg.getBoundingClientRect();
    return (event.clientY - box.top) * (svg.viewBox.baseVal.height / box.height);
  }

  /**
   * @param {PointerEvent} event a pointerdown on a limit line.
   * @param {SVGElement} node the line's group.
   * Grabs the line nearest to the pointer, as the hit strokes of lines a few points apart overlap.
   */
  function limitGrab(event, node) {
    if (event.button !== 0 || limitView.saving) {
      return;
    }
    event.preventDefault();
    const svg = node.ownerSVGElement;
    const at = limitChartY(event, svg);
    const gap = (line) => Math.abs(Number(line.querySelector(".res-limit-mark").getAttribute("y1")) - at);
    const grabbed = [...svg.querySelectorAll("g.res-limit")].reduce((best, line) => (gap(line) < gap(best) ? line : best), node);
    // A synthetic pointerdown names no active pointer, and capturing it throws NotFoundError.
    if (event.isTrusted) {
      grabbed.setPointerCapture(event.pointerId);
    }
    grabbed.setAttribute("data-dragging", "");
    limitView.drag = {node: grabbed};
  }

  /**
   * @param {PointerEvent} event a pointermove over or captured by a limit line.
   * @param {SVGElement} node the line's group.
   * @param {Object} frame the chart frame of resourceFrame().
   * @param {Function} y maps a percent to the chart's y.
   * Stages the percent under the pointer and redraws only that line and the staged bar, so the capture survives.
   */
  function limitMove(event, node, frame, y) {
    if (!limitView.drag || limitView.drag.node !== node) {
      return;
    }
    const value = Limits.valueAt(limitChartY(event, node.ownerSVGElement), frame.top, frame.bottom);
    stageLimit(node.getAttribute("data-metric"), node.getAttribute("data-level"), value);
    limitPaint(node, frame, y);
    drawLimitBar();
  }

  function limitDrop() {
    if (!limitView.drag) {
      return;
    }
    limitView.drag = null;
    drawResources();
  }

  /**
   * @param {KeyboardEvent} event a key on a focused limit line: the arrows move it by 1, Page Up and Down by 5, Escape
   * drops its staged value.
   * @param {string} metric one of Limits.METRICS.
   * @param {string} level one of Limits.LEVELS.
   */
  function limitKey(event, metric, level) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      stageLimit(metric, level, limitsHeld()[metric][level]);
    } else if (Object.hasOwn(LIMIT_STEPS, event.key)) {
      event.preventDefault();
      const value = limitValue(metric, level);
      stageLimit(metric, level, Math.min(100, Math.max(0, Math.round(Number.isFinite(value) ? value : 0) + LIMIT_STEPS[event.key])));
    } else {
      return;
    }
    drawResources();
  }

  function limitLine(frame, y, metric, level) {
    const node = s("g", {"data-metric": metric, "data-level": level, "data-line": level, role: "slider", tabindex: 0, "aria-valuemin": 0, "aria-valuemax": 100, "aria-orientation": "vertical", on: {
      pointerdown: (event) => limitGrab(event, node),
      pointermove: (event) => limitMove(event, node, frame, y),
      pointerup: limitDrop,
      pointercancel: limitDrop,
      lostpointercapture: limitDrop,
      keydown: (event) => limitKey(event, metric, level),
    }});
    limitPaint(node, frame, y);
    return node;
  }

  /**
   * @param {Object} frame the chart frame of resourceFrame().
   * @param {Function} y maps a percent to the chart's y.
   */
  function limitLines(frame, y) {
    const data = limitView.data;
    if (!data || !data.limits || !resourceView.show.limits) {
      return;
    }
    const metric = limitView.metric;
    const name = Limits.NAMES[metric];
    const shown = limitShown();
    const target = Limits.TARGETED.includes(metric) && data.target ? data.target[metric] : null;
    if (typeof target === "number" && shown.target) {
      const at = fixed(y(target));
      frame.svg.append(s("g", {class: "res-target", "data-metric": metric, "data-value": String(target)}, s("title", {}, `${name} target ${target.toFixed(1)} %: ${Limits.meaning("target")}`),
        s("line", {x1: RESOURCE.left, x2: fixed(frame.right), y1: at, y2: at}), s("text", {x: RESOURCE.left + LIMIT_LABEL.inset, y: fixed(y(target) - LIMIT_LABEL.gap)}, `target ${Math.round(target)}`)));
    }
    for (const level of Limits.LEVELS.filter((entry) => shown[entry])) {
      frame.svg.append(limitLine(frame, y, metric, level));
    }
  }

  /**
   * @param {MouseEvent} event a right click on the Hardware chart; it opens the matrix in place of the context menu.
   */
  function limitContext(event) {
    if (limitsHeld()) {
      event.preventDefault();
      openLimits();
    }
  }

  /**
   * @param {Object} next valid limits to save.
   * @param {string} label what the passkey prompt and the toast name.
   * @returns {Promise<boolean>} whether the hub saved them: a value that stays or tightens saves at once, a looser one
   * only once the passkey signs the whole object in one assertion; a canceled passkey sends nothing and keeps the old
   * values and the staged ones.
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
    limitView.staged = {};
    toast(label, [loose.length ? "Signed and saved to limits.json" : "Saved to limits.json"], true);
    drawResources();
    return true;
  }

  async function saveStaged() {
    const review = limitReview();
    if (!review || review.broken || !review.changes.length || limitView.saving) {
      return;
    }
    limitView.saving = true;
    drawLimitBar();
    const count = review.changes.length;
    await saveLimits(review.next, `Save ${count} limit change${count === 1 ? "" : "s"} (${review.changes.map(Limits.said).join(", ")})`);
    limitView.saving = false;
    drawResources();
  }

  function discardStaged() {
    limitView.staged = {};
    drawResources();
  }

  async function chooseProfile(id, label) {
    const data = limitView.data;
    if (data && !limitView.saving && Limits.profileOf(data.limits, data.profiles) !== id) {
      await saveLimits(data.profiles[id], `Profile ${label}`);
    }
  }

  function openLimits() {
    const data = limitView.data;
    const held = limitsHeld();
    if (!held) {
      return;
    }
    limitView.cells = [];
    const cell = (metric, level) => {
      const input = h("input", {type: "number", class: "limit-cell", min: 0, max: 100, step: 1, value: String(limitValue(metric, level)), "data-metric": metric, "data-level": level, "aria-label": `${Limits.NAMES[metric]} ${Limits.LEVEL_NAMES[level]} in percent`, on: {input: () => {
        stageLimit(metric, level, input.valueAsNumber);
        drawResources();
      }}});
      limitView.cells.push(input);
      return h("td", {}, input);
    };
    const rows = Limits.METRICS.map((metric) => h("tr", {"data-metric": metric}, h("th", {scope: "row"}, Limits.NAMES[metric]), Limits.LEVELS.map((level) => cell(metric, level))));
    limitView.sheet = limitStageBar();
    openSheet("Limits", h("div", {class: "stack limits-sheet"},
      h("p", {class: "muted"}, data.limits ? `limits.json in the council directory, ${Limits.ORDER} per metric. A changed value is staged beside the lines; Save sends them all, and a looser one needs the passkey.` : "No limits.json yet, so the queue config applies: the table shows Balanced, and the first save needs the passkey."),
      data.why ? h("p", {class: "limit-error", role: "alert"}, revealed(data.why)) : null,
      h("div", {class: "table-wrap"}, h("table", {class: "limits-table", "aria-label": "Limits"},
        h("thead", {}, h("tr", {}, h("th", {scope: "col"}, "Metric"), Limits.LEVELS.map((level) => h("th", {scope: "col", "data-level": level, title: Limits.meaning(level)}, Limits.LEVEL_NAMES[level])))),
        h("tbody", {}, rows))),
      limitView.sheet.root), false);
    drawLimitBar();
  }
