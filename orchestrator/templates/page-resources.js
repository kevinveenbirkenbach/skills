  const RESOURCE = {left: 46, right: 10, wide: 50, top: 6, bottom: 6, axis: 18, poll: 5000, stale: 60, tones: 6, glyph: 6.5, shown: 100, lane: 13};
  const RESOURCE_PANELS = [["hardware", "bi-cpu", "Hardware: disks, CPU, RAM, swap, GPU and VRAM"], ["tokens", "bi-coin", "Tokens per agent"], ["combined", "bi-layers", "Hardware, tokens and burnup"]];
  const HARDWARE_TONES = {shades: 3, host: {CPU: "res-cpu", RAM: "res-ram", Swap: "res-swap"}};
  const RESOURCE_ZONES = {idle: "Idle: below 30 %", saturated: "Saturated: above 90 %"};
  const RESOURCE_MARKS = {
    wait: ["#bi-hourglass-split", (mark) => `Idle waiting: ${mark.peak} jobs waited while CPU and RAM stayed under 50 %`, 0],
    blocked: ["#bi-sign-stop", (mark) => revealed(`${mark.head} waited ${Math.round(mark.peak / 60)} min: ${mark.reason}`), 1],
    hung: ["#bi-pause-circle", (mark) => revealed(`suspect hung: ${mark.hung.join(", ")}`), 2],
    asleep: ["#bi-moon", (mark) => `${mark.name} asleep`, 0],
    unknown: ["#bi-question-circle", (mark) => revealed(`${mark.name} unknown: ${mark.causes.length ? mark.causes.join("; ") : "no reading"}`), 0],
  };
  const RESOURCE_BURN = {done: "Done", scope: "Scope"};
  const RESOURCE_PICKS = [["hardware", "Hardware"], ["tokens", "Tokens"], ["combined", "Combined"], ["accounts", "Accounts"], ["usage", "Usage"]];
  const RESOURCE_SHOW = [
    ["legend", "Legend", "the series chips above each chart; a chip still switches its series on and off"],
    ["queue", "Queue markers", "the spans of a queue head blocked for 10 minutes and of suspect hung jobs"],
    ["waits", "Wait bands", "the spans where jobs waited while CPU and RAM stayed under 50 %"],
    ["limits", "Limit lines", "lower, upper, STOP, MAYDAY and the live target of the picked metric"],
  ];
  const RESOURCE_SHOW_KEY = "kvb-orchestrator.resources-view";
  const RESOURCE_SHOW_MARKS = {wait: "waits", blocked: "queue", hung: "queue"};
  const resourceView = {data: null, dom: null, busy: false, key: "", at: 0, timer: 0, series: {}, show: {legend: true, queue: true, waits: true, limits: true}};
  const resourceShowOf = (value) => Object.fromEntries(RESOURCE_SHOW.map(([key]) => [key, !(value && value[key] === false)]));
  const resourceKey = () => JSON.stringify([ui.preset, ui.asOf]);
  const resourcesStale = () => resourceKey() !== resourceView.key || nowSeconds() - resourceView.at >= RESOURCE.stale;
  const compactCount = Resources.compact;
  const resourceLabel = (line) => (line.kind === "vram" ? `${line.name} VRAM` : line.name);
  const percentOf = (value) => `${value} %`;

  function resourceSwitch(key, next, name, label, hint) {
    const path = `resources.${key}`;
    return h("button", {type: "button", class: "btn small soft res-switch", "data-switch": key, "aria-pressed": "false", ...named(label, hint), on: {click: () => ViewStore.set(path, next(ViewStore.get(path)))}}, icon(name), h("span", {}, label));
  }

  function resourcePicks() {
    const boxes = RESOURCE_PICKS.map(([kind, label]) => {
      const box = h("input", {type: "checkbox", "data-pick": kind, "aria-label": label, on: {change: () => ViewStore.update("resources.panels", (list) => [...list.filter((name) => name !== kind), ...(box.checked ? [kind] : [])])}});
      return {kind, box, row: h("label", {class: "menu-item res-pick"}, box, h("span", {}, label))};
    });
    const menu = h("details", {class: "menu res-panels-menu"}, h("summary", {...named("Panels", "Panels: choose which panels Resources shows; the last one stays on")}, icon("bi-grid"), h("span", {}, "Panels"), caret()),
      h("div", {class: "menu-box end", role: "group", "aria-label": "Panels"}, boxes.map((entry) => entry.row)));
    return {menu, boxes};
  }

  /**
   * @returns {Object} {menu, boxes}: the View menu, a checkbox each for the legend, the queue markers, the wait bands
   * and the limit lines, every choice kept in this browser.
   */
  function resourceShowMenu() {
    const boxes = RESOURCE_SHOW.map(([key, label, hint]) => {
      const box = h("input", {type: "checkbox", "data-show": key, "aria-label": label, on: {change: () => {
        resourceView.show = {...resourceView.show, [key]: box.checked};
        keep(RESOURCE_SHOW_KEY, resourceView.show);
        drawResources();
      }}});
      return {key, box, row: h("label", {class: "menu-item res-pick", title: `${label}: ${hint}`}, box, h("span", {}, label))};
    });
    const menu = h("details", {class: "menu res-view-menu"}, h("summary", {...named("View", "View: show or hide the legend, the queue markers, the wait bands and the limit lines; this browser keeps the choice")}, icon("bi-eye"), h("span", {}, "View"), caret()),
      h("div", {class: "menu-box end", role: "group", "aria-label": "View"}, boxes.map((entry) => entry.row)));
    return {menu, boxes};
  }

  function resourcesScreen() {
    const count = h("span", {class: "count", title: "Samples", "aria-label": "Samples"}, "0");
    const switches = {
      tokens: resourceSwitch("tokens", (mode) => (mode === "accumulated" ? "interval" : "accumulated"), "bi-graph-up-arrow", "Accumulated", "Accumulated: per-agent running sums of the tokens instead of the tokens per hour"),
    };
    const picks = resourcePicks();
    resourceView.show = resourceShowOf(stored(RESOURCE_SHOW_KEY, null));
    const shows = resourceShowMenu();
    const panels = RESOURCE_PANELS.map(([kind, name, label]) => {
      const legend = h("div", {class: "res-legend"});
      const plot = h("div", {class: "res-plot", ...(kind === "hardware" ? {on: {contextmenu: limitContext}} : {})});
      const panel = h("section", {class: `card res-panel res-${kind}`, "data-panel": `resources-${kind}`, "aria-label": label, hidden: kind === "combined"},
        h("div", {class: "res-head", "data-legend-slot": ""}, h("span", {class: "res-title", title: label, "aria-label": label}, icon(name)), legend), kind === "hardware" ? limitBar() : null, plot);
      return {kind, label, legend, plot, panel};
    });
    const accounts = accountsPanel();
    const usage = usagePanel();
    resourceView.dom = {count, switches, picks, shows, panels, accounts, usage};
    if (!resourceView.timer) {
      resourceView.timer = window.setInterval(pollResources, RESOURCE.poll);
      window.addEventListener("resize", drawResources);
      ViewStore.on("resources", drawResources);
    }
    window.setTimeout(() => {
      drawResources();
      fetchResources();
      fetchAccounts();
    }, 0);
    const reload = iconBtn("bi-arrow-clockwise", "Reload", "btn small soft", () => {
      fetchResources();
      fetchAccounts();
      if (!usage.panel.hidden) {
        fetchUsage();
      }
    }, "Reload: read the sampler files, the accounts and the usage again");
    return h("div", {class: "graph resources"},
      boxHead("Resources", "", h("div", {class: "toolbar"}, reload, switches.tokens, picks.menu, shows.menu, count)),
      h("div", {class: "res-panels"}, panels.map((entry) => entry.panel), accounts.panel, usage.panel));
  }

  function pollResources() {
    const dom = resourceView.dom;
    if (!dom || !dom.count.isConnected || document.hidden || resourceView.busy) {
      return;
    }
    if (resourcesStale()) {
      fetchResources();
    }
  }

  async function fetchResources() {
    if (resourceView.busy) {
      return;
    }
    resourceView.busy = true;
    resourceView.key = resourceKey();
    fetchLimits();
    try {
      const response = await fetch(`/api/resources?${windowQuery()}`, {cache: "no-store"});
      if (response.ok) {
        resourceView.data = await response.json();
      }
    } catch {
      ui.offline = true;
    }
    resourceView.at = nowSeconds();
    resourceView.busy = false;
    drawResources();
  }

  function resourceFrame(entry, span, size, dual) {
    const axis = entry.kind !== "hardware";
    const right = size.width - (dual ? RESOURCE.wide : RESOURCE.right);
    const bottom = size.height - (axis ? RESOURCE.axis : RESOURCE.bottom);
    const x = (t) => RESOURCE.left + ((Math.min(Math.max(t, span.from), span.to) - span.from) / (span.to - span.from)) * (right - RESOURCE.left);
    const svg = s("svg", {class: `chart res-chart res-${entry.kind}`, "data-chart": entry.kind, "data-from": span.from, "data-to": span.to, viewBox: `0 0 ${size.width} ${size.height}`, role: "img", "aria-label": entry.label});
    const ticks = resourceTicks(span, right - RESOURCE.left);
    for (let index = 0; index <= ticks.count; index += 1) {
      const t = span.from + ((span.to - span.from) * index) / ticks.count;
      svg.append(s("line", {class: "grid", x1: fixed(x(t)), x2: fixed(x(t)), y1: RESOURCE.top, y2: fixed(bottom)}));
      if (axis && (ticks.all || index === ticks.count)) {
        svg.append(s("text", {class: "axis", "data-axis": "time", x: fixed(x(t)), y: size.height - 4, "text-anchor": index === 0 ? "start" : index === ticks.count ? "end" : "middle"}, ticks.format.format(stampOf(t))));
      }
    }
    return {svg, x, top: RESOURCE.top, bottom, right};
  }

  /**
   * @param span - {from, to} of the chart in epoch seconds.
   * @param room - the plot width in px.
   * @returns {count, all, format}: up to 4 intervals between time labels, as many as fit apart at RESOURCE.glyph px
   * per character, all false when not even the first and the last label fit, so that only the last is drawn.
   */
  function resourceTicks(span, room) {
    const format = span.to - span.from > DAY ? absolute : clock;
    const wide = Math.max(...[span.from, span.to].map((t) => format.format(stampOf(t)).length)) * RESOURCE.glyph + RESOURCE.glyph;
    const fits = (count) => room / count >= wide * (count === 1 ? 2 : 1.5);
    const count = [4, 3, 2, 1].find(fits);
    return {count: count || 1, all: Boolean(count), format};
  }

  function resourceScale(frame, values, label, side) {
    const y = (value) => frame.top + (1 - value / values[values.length - 1]) * (frame.bottom - frame.top);
    const left = side === "left";
    for (const value of values) {
      if (left) {
        frame.svg.append(s("line", {class: "grid", x1: RESOURCE.left, x2: fixed(frame.right), y1: fixed(y(value)), y2: fixed(y(value))}));
      }
      frame.svg.append(s("text", {class: `axis ${side}`, "data-axis": side, x: left ? RESOURCE.left - 6 : fixed(frame.right + 6), y: fixed(y(value)), dy: "0.35em", "text-anchor": left ? "end" : "start"}, label(value)));
    }
    return y;
  }

  function resourceBackdrop(frame, y, marks, span) {
    for (const zone of Resources.ZONES) {
      frame.svg.append(s("rect", {class: `band ${zone.kind}`, "data-zone": zone.kind, x: RESOURCE.left, width: fixed(frame.right - RESOURCE.left), y: fixed(y(zone.to)), height: fixed(y(zone.from) - y(zone.to))}, s("title", {}, RESOURCE_ZONES[zone.kind])));
    }
    for (const mark of marks) {
      const left = frame.x(Math.max(mark.from, span.from));
      const right = frame.x(Math.min(mark.to, span.to));
      if (right <= left) {
        continue;
      }
      const [href, words, lane] = RESOURCE_MARKS[mark.kind];
      const press = (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          resourceQueueSheet(mark);
        }
      };
      const open = mark.steps ? {role: "button", tabindex: 0, "aria-label": words(mark), on: {click: () => resourceQueueSheet(mark), keydown: press}} : {};
      frame.svg.append(s("rect", {class: `res-mark ${mark.kind}`, "data-from": mark.from, "data-to": mark.to, "data-peak": mark.peak, x: fixed(left), width: fixed(Math.max(right - left, 2)), y: frame.top, height: fixed(frame.bottom - frame.top), ...open}, s("title", {}, words(mark))));
      frame.svg.append(s("use", {class: `res-icon ${mark.kind}`, href, x: fixed(left + 2), y: frame.top + 2 + lane * RESOURCE.lane, width: 11, height: 11}));
    }
  }

  /**
   * @param mark - a blocked or hung mark: {kind, from, to, peak, steps, hung} and for blocked head.
   */
  function resourceQueueSheet(mark) {
    const time = (t) => absolute.format(stampOf(t));
    const title = mark.kind === "blocked" ? `${mark.head} waited ${Math.round(mark.peak / 60)} min` : `Suspect hung: ${mark.hung.join(", ")}`;
    const steps = mark.steps.map((step) => h("li", {"data-head": step.id, "data-from": step.from, "data-to": step.to},
      h("div", {class: "row"}, h("code", {}, revealed(step.id)), h("span", {class: "muted"}, `${time(step.from)} to ${time(step.to)}`)),
      h("p", {class: "text"}, revealed(step.reason === "" ? "no reason given" : step.reason))));
    const hung = mark.hung.map((id) => h("li", {"data-hung": id}, h("code", {}, revealed(id))));
    openSheet(title, [
      h("p", {class: "muted"}, `${time(mark.from)} to ${time(mark.to)}`),
      h("h3", {}, "Queue head", counter(steps.length)),
      steps.length ? h("ul", {class: "mini"}, steps) : h("p", {class: "muted"}, "No job waited at the head of the queue."),
      h("h3", {}, "Suspect hung", counter(hung.length)),
      hung.length ? h("ul", {class: "mini"}, hung) : h("p", {class: "muted"}, "No active job was suspect hung."),
    ], false);
  }

  function resourceLines(frame, y, list) {
    for (const line of list) {
      for (const part of Resources.segments(line.points)) {
        const d = part.map(([t, value], index) => `${index ? "L" : "M"}${fixed(frame.x(t))},${fixed(y(Math.min(Math.max(value, 0), 100)))}`).join(" ");
        frame.svg.append(s("path", {class: `res-line ${line.tone}`, "data-id": line.id, "data-series": line.name, "data-kind": line.kind, "data-points": part.length, d: part.length === 1 ? `${d} h1` : d}, s("title", {}, line.label)));
      }
    }
  }

  function resourceSteps(frame, y, points) {
    return points.map(([t, value], index) => (index ? `H${fixed(frame.x(t))} V${fixed(y(value))}` : `M${fixed(frame.x(t))},${fixed(y(value))}`)).join(" ");
  }

  function tokenPlot(rows, mode) {
    if (mode === "accumulated") {
      const sums = Resources.accumulate(rows);
      return {mode, top: Math.max(sums.top, 1), sums};
    }
    const stack = Resources.stack(rows);
    return {mode, top: Math.max(stack.top, 1), stack};
  }

  function tokenMarks(frame, y, plot, tones, span, faint) {
    if (plot.mode === "accumulated") {
      for (const line of plot.sums.lines) {
        const last = line.points[line.points.length - 1][1];
        frame.svg.append(s("path", {class: `res-sum res-c${tones.get(line.agent)}`, "data-agent": line.agent, "data-last": last, "data-points": JSON.stringify(line.points.map(([, value]) => value)), d: resourceSteps(frame, y, line.points)},
          s("title", {}, `${line.agent}: ${last} tokens summed up in the window`)));
      }
      return;
    }
    for (const bar of plot.stack.bars) {
      const left = frame.x(Math.max(bar.t, span.from));
      const right = frame.x(Math.min(bar.t + Resources.HOUR, span.to));
      if (right <= left) {
        continue;
      }
      for (const part of bar.parts) {
        const words = `${part.agent} · ${absolute.format(stampOf(bar.t))}: ${part.total} tokens (input ${part.input}, output ${part.output}, cache read ${part.cache_read}, cache write ${part.cache_write}) · ${part.models.join(", ")}`;
        frame.svg.append(s("rect", {class: `res-bar res-c${tones.get(part.agent)}${faint ? " faint" : ""}`, "data-agent": part.agent, "data-t": bar.t, "data-total": part.total, x: fixed(left), width: fixed(Math.max(right - left - 1, 1)), y: fixed(y(part.to)), height: fixed(Math.max(y(part.from) - y(part.to), 0.5))}, s("title", {}, words)));
      }
    }
  }

  /**
   * @param samples - sampler rows.
   * @returns the hardware lines, each with its tone: the disks in shades of one hue, CPU, RAM and swap each in its own
   * hue, every GPU in shades of a further hue and its VRAM in yet another, so that no two kinds share a colour.
   */
  function hardwareSeries(samples) {
    const shades = {disk: new Map(), util: new Map(), vram: new Map()};
    return Resources.hardware(samples).map((line) => {
      const shade = shades[line.kind];
      if (shade && !shade.has(line.name)) {
        shade.set(line.name, shade.size % HARDWARE_TONES.shades);
      }
      const tone = shade ? `res-${line.kind}${shade.get(line.name)}` : HARDWARE_TONES.host[line.name];
      const last = [...line.points].reverse().find(([, value]) => value !== null);
      return {...line, id: ViewStore.id(line.kind, line.name), label: `${resourceLabel(line)} ${dash(last === undefined ? null : last[1])} %`, tone: `${tone} k-${line.kind}`};
    });
  }

  function agentSeries(tokens) {
    const full = Resources.stack(tokens);
    const tones = new Map(full.agents.map((agent, index) => [agent, index % RESOURCE.tones]));
    const list = full.agents.map((agent) => ({id: ViewStore.id("agent", agent), agent, label: `${agent} ${compactCount(full.totals[agent])}`, tone: `res-c${tones.get(agent)}`}));
    return {list, tones};
  }

  function burnSeries(span) {
    const picked = Plan.scoped(state.tasks, "filter", {filtered: state.tasks, since: span.from, until: span.to, now: state.now, holders: {}});
    const scaled = Resources.burnup(Plan.burn(picked.rows, {estimation: settings.estimation, from: span.from, to: span.to}).points);
    return Object.entries(RESOURCE_BURN).map(([name, word]) => {
      const points = scaled[name];
      const last = points.length ? points[points.length - 1][1] : 0;
      return {id: ViewStore.id("burn", name), name, points, label: `${word} ${Math.round(last)} %`, tone: `res-burn k-${name}`, top: scaled.top};
    });
  }

  function shownRows(tokens, agents, hidden) {
    const gone = new Set(agents.list.filter((entry) => hidden.has(entry.id)).map((entry) => entry.agent));
    return tokens.filter((row) => !gone.has(row.agent));
  }

  function hardwareChart(entry, parts, span, size) {
    const frame = resourceFrame(entry, span, size, false);
    const y = resourceScale(frame, [0, 50, 100], percentOf, "left");
    resourceBackdrop(frame, y, parts.marks, span);
    resourceLines(frame, y, parts.hardware.filter((line) => !parts.hidden.has(line.id)));
    limitLines(frame, y);
    return {svg: frame.svg, series: RESOURCE_SERIES.hardware(parts), path: "resources.hidden"};
  }

  function tokensChart(entry, parts, span, size) {
    const frame = resourceFrame(entry, span, size, false);
    const plot = tokenPlot(shownRows(parts.tokens, parts.agents, parts.hidden), parts.mode);
    const y = resourceScale(frame, [0, plot.top], compactCount, "left");
    tokenMarks(frame, y, plot, parts.agents.tones, span, false);
    return {svg: frame.svg, series: RESOURCE_SERIES.tokens(parts), path: "resources.hidden"};
  }

  function combinedChart(entry, parts, span, size) {
    const frame = resourceFrame(entry, span, size, true);
    const y = resourceScale(frame, [0, 50, 100], percentOf, "left");
    resourceBackdrop(frame, y, parts.marks, span);
    const plot = tokenPlot(shownRows(parts.tokens, parts.agents, parts.combinedHidden), parts.mode);
    tokenMarks(frame, resourceScale(frame, [0, plot.top], compactCount, "right"), plot, parts.agents.tones, span, true);
    resourceLines(frame, y, parts.hardware.filter((line) => !parts.combinedHidden.has(line.id)));
    for (const line of parts.burn.filter((item) => !parts.combinedHidden.has(item.id) && item.points.length)) {
      frame.svg.append(s("path", {class: line.tone, "data-id": line.id, "data-series": line.name, "data-last": line.points[line.points.length - 1][1], "data-top": line.top, d: resourceSteps(frame, y, line.points)}, s("title", {}, `${line.label} of the largest scope in the window (${line.top})`)));
    }
    return {svg: frame.svg, series: RESOURCE_SERIES.combined(parts), path: "resources.combinedHidden"};
  }

  const RESOURCE_CHARTS = {hardware: hardwareChart, tokens: tokensChart, combined: combinedChart};
  const RESOURCE_SERIES = {hardware: (parts) => parts.hardware, tokens: (parts) => parts.agents.list, combined: (parts) => [...parts.hardware, ...parts.agents.list, ...parts.burn]};
  const resourceSmall = (size) => size.width < RESOURCE.left + RESOURCE.wide + 10 || size.height < RESOURCE.axis + 10;

  /**
   * @param kind - hardware, tokens or combined.
   * @returns the metric pin the chart's star makes now: {kind: "metric", id, view}, view being the chart, its token
   * mode and the sorted ids of the series switched on, null while all are on; the id names the chart, the mode and
   * all or a digest of the series, so another selection is another pin. With more than RESOURCE.shown series on but
   * not all, the pin also carries refused, as the view store keeps at most that many.
   */
  function resourcePin(kind) {
    const drawn = resourceView.series[kind] || {ids: [], shown: [], tokens: ViewStore.get("resources").tokens};
    const shown = [...drawn.shown].sort();
    const view = {chart: kind, tokens: kind === "hardware" ? "interval" : drawn.tokens, shown: shown.length === drawn.ids.length ? null : shown};
    const id = [kind, kind === "hardware" ? "" : view.tokens, view.shown === null ? "all" : Panels.digest(shown.join("\n"))].filter(Boolean).join("/");
    const over = view.shown !== null && view.shown.length > RESOURCE.shown;
    return over ? {kind: "metric", id, view, refused: `more than ${RESOURCE.shown} series are switched on: switch some off, or all of them on`} : {kind: "metric", id, view};
  }

  /**
   * @param view - a metric pin's view: {chart, tokens, shown}.
   * @param size - {width, height} of the plot in px.
   * @returns {svg, series}: the chart drawn from the loaded samples with only the view's series, svg null when the
   * plot is too small, and those series for a legend.
   */
  function metricChart(view, size) {
    const {span, parts, series, hidden} = metricParts(resourceView.data, view);
    const [, , label] = RESOURCE_PANELS.find(([kind]) => kind === view.chart);
    const drawn = RESOURCE_CHARTS[view.chart]({kind: view.chart, label}, {...parts, hidden, combinedHidden: hidden}, span, size);
    return {svg: resourceSmall(size) ? null : drawn.svg, series: series.filter((line) => !hidden.has(line.id))};
  }

  function metricParts(data, view) {
    const span = {from: data.since, to: Math.max(data.until, data.since + 60)};
    const parts = resourceParts(data, {tokens: view.tokens, hidden: [], combinedHidden: [], panels: [view.chart]}, span);
    const series = RESOURCE_SERIES[view.chart](parts);
    return {span, parts, series, hidden: new Set(view.shown === null ? [] : series.map((line) => line.id).filter((id) => !view.shown.includes(id)))};
  }

  /**
   * @param view - a metric pin's view: {chart, tokens, shown}.
   * @returns false while no samples are loaded; else true.
   */
  function resourceRestore(view) {
    if (resourceView.data === null) {
      return false;
    }
    const {series, hidden} = metricParts(resourceView.data, view);
    const ids = new Set(series.map((line) => line.id));
    ViewStore.update(view.chart === "combined" ? "resources.combinedHidden" : "resources.hidden", (list) => [...list.filter((id) => !ids.has(id)), ...hidden]);
    ViewStore.update("resources.panels", (list) => (list.includes(view.chart) ? list : [...list, view.chart]));
    if (view.chart !== "hardware") {
      ViewStore.set("resources.tokens", view.tokens);
    }
    return true;
  }

  function resourceParts(data, view, span) {
    return {
      hardware: hardwareSeries(data.samples),
      agents: agentSeries(data.tokens),
      tokens: data.tokens,
      mode: view.tokens,
      hidden: new Set(view.hidden),
      combinedHidden: new Set(view.combinedHidden),
      burn: view.panels.includes("combined") ? burnSeries(span) : [],
      marks: [
        ...Resources.waits(data.samples).map((mark) => ({...mark, kind: "wait"})),
        ...Resources.blocked(data.samples).map((mark) => ({...mark, kind: "blocked"})),
        ...Resources.hung(data.samples).map((mark) => ({...mark, kind: "hung"})),
        ...["asleep", "unknown"].flatMap((kind) => Resources[kind](data.samples).flatMap((gpu) => gpu.spans.map((mark) => ({...mark, kind, name: gpu.name})))),
      ],
    };
  }

  function drawResources() {
    const dom = resourceView.dom;
    const data = resourceView.data;
    if (!dom || !dom.count.isConnected || limitView.drag) {
      return;
    }
    const view = ViewStore.get("resources");
    dom.switches.tokens.setAttribute("aria-pressed", String(view.tokens === "accumulated"));
    for (const {key, box} of dom.shows.boxes) {
      box.checked = resourceView.show[key];
    }
    for (const {kind, box} of dom.picks.boxes) {
      box.checked = view.panels.includes(kind);
      box.disabled = box.checked && view.panels.length === 1;
      box.title = box.disabled ? "The last panel stays on" : "";
    }
    for (const entry of dom.panels) {
      entry.panel.hidden = !view.panels.includes(entry.kind);
    }
    dom.accounts.panel.hidden = !view.panels.includes("accounts");
    drawAccounts();
    dom.usage.panel.hidden = !view.panels.includes("usage");
    if (!dom.usage.panel.hidden && usageView.ask === 0) {
      fetchUsage();
    }
    drawUsage();
    drawLimitBar();
    if (data === null) {
      return;
    }
    const active = document.activeElement;
    const focused = active && typeof active.getAttribute === "function" ? active.getAttribute("data-chip") : null;
    const line = active && typeof active.getAttribute === "function" ? active.getAttribute("data-line") : null;
    const span = {from: data.since, to: Math.max(data.until, data.since + 60)};
    const parts = resourceParts(data, view, span);
    parts.marks = parts.marks.filter((mark) => !Object.hasOwn(RESOURCE_SHOW_MARKS, mark.kind) || resourceView.show[RESOURCE_SHOW_MARKS[mark.kind]]);
    dom.count.textContent = String(data.samples.length);
    for (const entry of dom.panels) {
      if (entry.panel.hidden) {
        entry.plot.replaceChildren();
        entry.legend.replaceChildren();
        continue;
      }
      const box = entry.plot.getBoundingClientRect();
      const size = {width: Math.round(box.width), height: Math.round(box.height)};
      const drawn = RESOURCE_CHARTS[entry.kind](entry, parts, span, size);
      const hidden = drawn.path === "resources.hidden" ? parts.hidden : parts.combinedHidden;
      resourceView.series[entry.kind] = {ids: drawn.series.map((line) => line.id), shown: drawn.series.map((line) => line.id).filter((id) => !hidden.has(id)), tokens: view.tokens};
      entry.plot.replaceChildren(...(resourceSmall(size) ? [] : [drawn.svg]));
      entry.legend.replaceChildren(LegendChips.render(drawn.series, drawn.path, "hidden"));
      entry.legend.hidden = !resourceView.show.legend;
      const chip = focused === null ? null : [...entry.legend.querySelectorAll("[data-chip]")].find((node) => node.getAttribute("data-chip") === focused);
      if (chip) {
        chip.focus();
      }
      const limit = line === null || entry.kind !== "hardware" ? null : entry.plot.querySelector(`g.res-limit[data-line="${line}"]`);
      if (limit) {
        limit.focus();
      }
    }
  }
