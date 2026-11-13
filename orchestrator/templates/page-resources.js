  const RESOURCE = {left: 46, right: 10, wide: 50, top: 6, bottom: 6, axis: 18, poll: 5000, stale: 60, tones: 6, narrow: 600};
  const RESOURCE_PANELS = [["hardware", "bi-cpu", "Hardware: disks, CPU, RAM, swap, GPU and VRAM"], ["tokens", "bi-coin", "Tokens per agent"], ["combined", "bi-layers", "Hardware, tokens and burnup"]];
  const RESOURCE_ZONES = {idle: "Idle: below 30 %", saturated: "Saturated: above 90 %"};
  const RESOURCE_MARKS = {
    wait: ["#bi-hourglass-split", (mark) => `${mark.peak} jobs waited while CPU and RAM stayed under 50 %`],
    asleep: ["#bi-moon", (mark) => `${mark.name} asleep`],
    unknown: ["#bi-question-circle", (mark) => `${mark.name} unknown: no reading`],
  };
  const RESOURCE_BURN = {done: "Done", scope: "Scope"};
  const resourceView = {data: null, dom: null, busy: false, key: "", at: 0, timer: 0};
  const resourceKey = () => JSON.stringify([ui.preset, ui.from, ui.to, ui.asOf]);
  const compactCount = (value) => (value >= 1e6 ? `${fixed(value / 1e6)}M` : value >= 1e3 ? `${fixed(value / 1e3)}k` : String(Math.round(value)));
  const resourceLabel = (line) => (line.kind === "vram" ? `${line.name} VRAM` : line.name);
  const percentOf = (value) => `${value} %`;

  function resourceSwitch(key, next, name, label, hint) {
    const path = `resources.${key}`;
    return h("button", {type: "button", class: "btn small soft res-switch", "data-switch": key, "aria-pressed": "false", ...named(label, hint), on: {click: () => ViewStore.set(path, next(ViewStore.get(path)))}}, icon(name), h("span", {}, label));
  }

  function resourcesScreen() {
    const count = h("span", {class: "count", title: "Samples", "aria-label": "Samples"}, "0");
    const switches = {
      tokens: resourceSwitch("tokens", (mode) => (mode === "accumulated" ? "interval" : "accumulated"), "bi-graph-up-arrow", "Accumulated", "Accumulated: per-agent running sums of the tokens instead of the tokens per hour"),
      combined: resourceSwitch("combined", (on) => !on, "bi-layers", "Combined", "Combined: hardware in %, tokens and the burnup in one chart"),
    };
    const panels = RESOURCE_PANELS.map(([kind, name, label]) => {
      const legend = h("div", {class: "res-legend"});
      const plot = h("div", {class: "res-plot"});
      const panel = h("section", {class: `card res-panel res-${kind}`, "data-panel": `resources-${kind}`, "aria-label": label, hidden: kind === "combined"},
        h("div", {class: "res-head"}, h("span", {class: "res-title", title: label, "aria-label": label}, icon(name)), legend), plot);
      return {kind, label, legend, plot, panel};
    });
    resourceView.dom = {count, switches, panels};
    if (!resourceView.timer) {
      resourceView.timer = window.setInterval(pollResources, RESOURCE.poll);
      window.addEventListener("resize", drawResources);
      ViewStore.on("resources", drawResources);
    }
    window.setTimeout(() => {
      drawResources();
      fetchResources();
    }, 0);
    const reload = iconBtn("bi-arrow-clockwise", "Reload", "btn small soft", fetchResources, "Reload: read the sampler files again");
    return h("div", {class: "graph resources"},
      h("div", {class: "card controls"}, h("div", {class: "toolbar", role: "toolbar", "aria-label": "Resources"}, reload, switches.tokens, switches.combined, count)),
      h("div", {class: "res-panels"}, panels.map((entry) => entry.panel)));
  }

  function pollResources() {
    const dom = resourceView.dom;
    if (!dom || !dom.count.isConnected || document.hidden || resourceView.busy) {
      return;
    }
    if (resourceKey() !== resourceView.key || nowSeconds() - resourceView.at >= RESOURCE.stale) {
      fetchResources();
    }
  }

  async function fetchResources() {
    if (resourceView.busy) {
      return;
    }
    resourceView.busy = true;
    resourceView.key = resourceKey();
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
    const ticks = size.width < RESOURCE.narrow ? 2 : 4;
    for (let index = 0; index <= ticks; index += 1) {
      const t = span.from + ((span.to - span.from) * index) / ticks;
      svg.append(s("line", {class: "grid", x1: fixed(x(t)), x2: fixed(x(t)), y1: RESOURCE.top, y2: fixed(bottom)}));
      if (axis) {
        svg.append(s("text", {class: "axis", x: fixed(x(t)), y: size.height - 4, "text-anchor": index === 0 ? "start" : index === ticks ? "end" : "middle"}, (span.to - span.from > DAY ? absolute : clock).format(stampOf(t))));
      }
    }
    return {svg, x, top: RESOURCE.top, bottom, right};
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
      const [href, words] = RESOURCE_MARKS[mark.kind];
      frame.svg.append(s("rect", {class: `res-mark ${mark.kind}`, "data-from": mark.from, "data-to": mark.to, "data-peak": mark.peak, x: fixed(left), width: fixed(Math.max(right - left, 2)), y: frame.top, height: fixed(frame.bottom - frame.top)}, s("title", {}, words(mark))));
      frame.svg.append(s("use", {class: `res-icon ${mark.kind}`, href, x: fixed(left + 2), y: frame.top + 2, width: 11, height: 11}));
    }
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

  function hardwareSeries(samples) {
    const tones = new Map();
    return Resources.hardware(samples).map((line) => {
      if (!tones.has(line.name)) {
        tones.set(line.name, tones.size % RESOURCE.tones);
      }
      const last = [...line.points].reverse().find(([, value]) => value !== null);
      return {...line, id: ViewStore.id(line.kind, line.name), label: `${resourceLabel(line)} ${dash(last === undefined ? null : last[1])} %`, tone: `res-c${tones.get(line.name)} k-${line.kind}`};
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
    return {svg: frame.svg, series: parts.hardware, path: "resources.hidden"};
  }

  function tokensChart(entry, parts, span, size) {
    const frame = resourceFrame(entry, span, size, false);
    const plot = tokenPlot(shownRows(parts.tokens, parts.agents, parts.hidden), parts.mode);
    const y = resourceScale(frame, [0, plot.top], compactCount, "left");
    tokenMarks(frame, y, plot, parts.agents.tones, span, false);
    return {svg: frame.svg, series: parts.agents.list, path: "resources.hidden"};
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
    return {svg: frame.svg, series: [...parts.hardware, ...parts.agents.list, ...parts.burn], path: "resources.combinedHidden"};
  }

  const RESOURCE_CHARTS = {hardware: hardwareChart, tokens: tokensChart, combined: combinedChart};

  function resourceParts(data, view, span) {
    return {
      hardware: hardwareSeries(data.samples),
      agents: agentSeries(data.tokens),
      tokens: data.tokens,
      mode: view.tokens,
      hidden: new Set(view.hidden),
      combinedHidden: new Set(view.combinedHidden),
      burn: view.combined ? burnSeries(span) : [],
      marks: [
        ...Resources.waits(data.samples).map((mark) => ({...mark, kind: "wait"})),
        ...["asleep", "unknown"].flatMap((kind) => Resources[kind](data.samples).flatMap((gpu) => gpu.spans.map((mark) => ({...mark, kind, name: gpu.name})))),
      ],
    };
  }

  function drawResources() {
    const dom = resourceView.dom;
    const data = resourceView.data;
    if (!dom || !dom.count.isConnected) {
      return;
    }
    const view = ViewStore.get("resources");
    dom.switches.tokens.setAttribute("aria-pressed", String(view.tokens === "accumulated"));
    dom.switches.combined.setAttribute("aria-pressed", String(view.combined));
    for (const entry of dom.panels) {
      entry.panel.hidden = (entry.kind === "combined") !== view.combined;
    }
    if (data === null) {
      return;
    }
    const active = document.activeElement;
    const focused = active && typeof active.getAttribute === "function" ? active.getAttribute("data-chip") : null;
    const span = {from: data.since, to: Math.max(data.until, data.since + 60)};
    const parts = resourceParts(data, view, span);
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
      const small = size.width < RESOURCE.left + RESOURCE.wide + 10 || size.height < RESOURCE.axis + 10;
      entry.plot.replaceChildren(...(small ? [] : [drawn.svg]));
      entry.legend.replaceChildren(LegendChips.render(drawn.series, drawn.path, "hidden"));
      const chip = focused === null ? null : [...entry.legend.querySelectorAll("[data-chip]")].find((node) => node.getAttribute("data-chip") === focused);
      if (chip) {
        chip.focus();
      }
    }
  }
