  const RESOURCE = {left: 46, right: 10, top: 6, bottom: 6, axis: 18, poll: 5000, stale: 60, tones: 6, hour: 3600, narrow: 600};
  const RESOURCE_PANELS = [["disks", "bi-hdd-stack", "Disks"], ["host", "bi-cpu", "CPU, RAM and swap"], ["gpu", "bi-gpu-card", "GPU and VRAM"], ["tokens", "bi-coin", "Tokens per agent"]];
  const RESOURCE_ZONES = {idle: "Idle: below 30 %", saturated: "Saturated: above 90 %"};
  const RESOURCE_MARKS = {
    wait: ["#bi-hourglass-split", (mark) => `${mark.peak} jobs waited while CPU and RAM stayed under 50 %`],
    asleep: ["#bi-moon", (mark) => `${mark.name} asleep`],
    unknown: ["#bi-question-circle", (mark) => `${mark.name} unknown: no reading`],
  };
  const resourceView = {data: null, dom: null, busy: false, key: "", at: 0, timer: 0};
  const resourceKey = () => JSON.stringify([ui.preset, ui.from, ui.to, ui.asOf]);
  const compactCount = (value) => (value >= 1e6 ? `${fixed(value / 1e6)}M` : value >= 1e3 ? `${fixed(value / 1e3)}k` : String(Math.round(value)));
  const resourceLabel = (line) => (line.kind === "vram" ? `${line.name} VRAM` : line.name);

  function resourcesScreen() {
    const count = h("span", {class: "count", title: "Samples", "aria-label": "Samples"}, "0");
    const panels = RESOURCE_PANELS.map(([kind, name, label]) => {
      const legend = h("div", {class: "res-legend"});
      const plot = h("div", {class: "res-plot"});
      const panel = h("section", {class: `card res-panel res-${kind}`, "data-panel": kind, "aria-label": label},
        h("div", {class: "res-head"}, h("span", {class: "res-title", title: label, "aria-label": label}, icon(name)), legend), plot);
      return {kind, label, legend, plot, panel};
    });
    resourceView.dom = {count, panels};
    if (!resourceView.timer) {
      resourceView.timer = window.setInterval(pollResources, RESOURCE.poll);
      window.addEventListener("resize", drawResources);
    }
    window.setTimeout(() => {
      drawResources();
      fetchResources();
    }, 0);
    const reload = iconBtn("bi-arrow-clockwise", "Reload", "btn small soft", fetchResources, "Reload: read the sampler files again");
    return h("div", {class: "graph resources"},
      h("div", {class: "card controls"}, h("div", {class: "toolbar", role: "toolbar", "aria-label": "Resources"}, reload, count)),
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

  function resourceFrame(entry, span, size) {
    const axis = entry.kind === "tokens";
    const bottom = size.height - (axis ? RESOURCE.axis : RESOURCE.bottom);
    const x = (t) => RESOURCE.left + ((t - span.from) / (span.to - span.from)) * (size.width - RESOURCE.left - RESOURCE.right);
    const svg = s("svg", {class: `chart res-chart res-${entry.kind}`, "data-panel": entry.kind, "data-from": span.from, "data-to": span.to, viewBox: `0 0 ${size.width} ${size.height}`, role: "img", "aria-label": entry.label});
    const ticks = size.width < RESOURCE.narrow ? 2 : 4;
    for (let index = 0; index <= ticks; index += 1) {
      const t = span.from + ((span.to - span.from) * index) / ticks;
      svg.append(s("line", {class: "grid", x1: fixed(x(t)), x2: fixed(x(t)), y1: RESOURCE.top, y2: fixed(bottom)}));
      if (axis) {
        svg.append(s("text", {class: "axis", x: fixed(x(t)), y: size.height - 4, "text-anchor": index === 0 ? "start" : index === ticks ? "end" : "middle"}, (span.to - span.from > DAY ? absolute : clock).format(stampOf(t))));
      }
    }
    return {svg, x, top: RESOURCE.top, bottom, right: size.width - RESOURCE.right};
  }

  function resourceScale(frame, values, label) {
    const y = (value) => frame.top + (1 - value / values[values.length - 1]) * (frame.bottom - frame.top);
    for (const value of values) {
      frame.svg.append(s("line", {class: "grid", x1: RESOURCE.left, x2: fixed(frame.right), y1: fixed(y(value)), y2: fixed(y(value))}));
      frame.svg.append(s("text", {class: "axis", x: RESOURCE.left - 6, y: fixed(y(value)), dy: "0.35em", "text-anchor": "end"}, label(value)));
    }
    return y;
  }

  function resourceMarks(frame, marks, span) {
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

  function resourcePercent(entry, list, marks, span, size) {
    const frame = resourceFrame(entry, span, size);
    const y = resourceScale(frame, [0, 50, 100], (value) => `${value} %`);
    for (const zone of Resources.ZONES) {
      frame.svg.append(s("rect", {class: `band ${zone.kind}`, "data-zone": zone.kind, x: RESOURCE.left, width: fixed(frame.right - RESOURCE.left), y: fixed(y(zone.to)), height: fixed(y(zone.from) - y(zone.to))}, s("title", {}, RESOURCE_ZONES[zone.kind])));
    }
    resourceMarks(frame, marks, span);
    const tones = new Map();
    const legend = [];
    for (const line of list) {
      if (!tones.has(line.name)) {
        tones.set(line.name, tones.size % RESOURCE.tones);
      }
      const tone = `res-c${tones.get(line.name)} k-${line.kind}`;
      const last = [...line.points].reverse().find(([, value]) => value !== null);
      const words = `${resourceLabel(line)} ${dash(last === undefined ? null : last[1])} %`;
      for (const part of Resources.segments(line.points)) {
        const d = part.map(([t, value], index) => `${index ? "L" : "M"}${fixed(frame.x(t))},${fixed(y(Math.min(Math.max(value, 0), 100)))}`).join(" ");
        frame.svg.append(s("path", {class: `res-line ${tone}`, "data-series": line.name, "data-kind": line.kind, "data-points": part.length, d: part.length === 1 ? `${d} h1` : d}, s("title", {}, words)));
      }
      legend.push(h("span", {class: `res-key ${tone}`, "data-series": line.name, "data-kind": line.kind}, words));
    }
    return {svg: frame.svg, legend};
  }

  function resourceTokens(entry, stack, span, size) {
    const frame = resourceFrame(entry, span, size);
    const y = resourceScale(frame, [0, Math.max(stack.top, 1)], compactCount);
    const tones = new Map(stack.agents.map((agent, index) => [agent, index % RESOURCE.tones]));
    for (const bar of stack.bars) {
      const left = frame.x(Math.max(bar.t, span.from));
      const right = frame.x(Math.min(bar.t + RESOURCE.hour, span.to));
      if (right <= left) {
        continue;
      }
      for (const part of bar.parts) {
        const words = `${part.agent} · ${absolute.format(stampOf(bar.t))}: ${part.total} tokens (input ${part.input}, output ${part.output}, cache read ${part.cache_read}, cache write ${part.cache_write}) · ${part.models.join(", ")}`;
        frame.svg.append(s("rect", {class: `res-bar res-c${tones.get(part.agent)}`, "data-agent": part.agent, "data-t": bar.t, "data-total": part.total, x: fixed(left), width: fixed(Math.max(right - left - 1, 1)), y: fixed(y(part.to)), height: fixed(Math.max(y(part.from) - y(part.to), 0.5))}, s("title", {}, words)));
      }
    }
    const legend = stack.agents.map((agent) => h("span", {class: `res-key res-c${tones.get(agent)}`, "data-series": agent}, `${agent} ${compactCount(stack.totals[agent])}`));
    return {svg: frame.svg, legend};
  }

  function drawResources() {
    const dom = resourceView.dom;
    const data = resourceView.data;
    if (!dom || !dom.count.isConnected || data === null) {
      return;
    }
    const span = {from: data.since, to: Math.max(data.until, data.since + 60)};
    const lines = Resources.lines(data.samples);
    const marks = {
      disks: [],
      host: Resources.waits(data.samples).map((mark) => ({...mark, kind: "wait"})),
      gpu: ["asleep", "unknown"].flatMap((kind) => Resources[kind](data.samples).flatMap((gpu) => gpu.spans.map((mark) => ({...mark, kind, name: gpu.name})))),
    };
    dom.count.textContent = String(data.samples.length);
    for (const entry of dom.panels) {
      const box = entry.plot.getBoundingClientRect();
      const size = {width: Math.round(box.width), height: Math.round(box.height)};
      if (size.width < RESOURCE.left + RESOURCE.right + 10 || size.height < RESOURCE.axis + 10) {
        entry.plot.replaceChildren();
        continue;
      }
      const drawn = entry.kind === "tokens" ? resourceTokens(entry, Resources.stack(data.tokens), span, size) : resourcePercent(entry, lines[entry.kind], marks[entry.kind], span, size);
      entry.plot.replaceChildren(drawn.svg);
      entry.legend.replaceChildren(...drawn.legend);
    }
  }
