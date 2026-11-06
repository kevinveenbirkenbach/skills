  function orbit() {
    const nodes = state.graph.nodes;
    positions = layout(nodes);
    const svg = chartFrame(400, "Orbit: Operator in der Mitte; wer zusammen arbeitet oder funkt, rückt zusammen, Stille driften nach außen");
    svg.append(...RINGS.map((r) => s("circle", {class: "ring", r})));
    const edgeLayer = s("g", {});
    const halos = new Map();
    for (const link of aggregate()) {
      const from = positions.get(link.source);
      const shade = tone(link.cls);
      const words = `${link.count}× ${CLASSES[link.cls] || link.cls}`;
      if (!from) {
        continue;
      }
      if (link.target === "*") {
        const index = halos.get(link.source) || 0;
        halos.set(link.source, index + 1);
        edgeLayer.append(s("circle", {class: `halo t-${shade}`, cx: fixed(from.x), cy: fixed(from.y), r: radiusOf(link.source) + 7 + index * 7, "stroke-width": width(link.count)},
          s("title", {}, `${link.source} an alle: ${words}`)));
        continue;
      }
      const to = positions.get(link.target);
      if (!to || to === from) {
        continue;
      }
      const control = Space.bend(from, to);
      const start = toward(from, control, radiusOf(link.source) + 2);
      const end = toward(to, control, radiusOf(link.target) + 4);
      edgeLayer.append(s("path", {class: `edge t-${shade}`, d: `M${fixed(start.x)},${fixed(start.y)} Q${fixed(control.x)},${fixed(control.y)} ${fixed(end.x)},${fixed(end.y)}`, "stroke-width": fixed(width(link.count)), "marker-end": `url(#tip-${shade})`},
        s("title", {}, `${link.source} → ${link.target}: ${words}`)));
    }
    const nodeLayer = s("g", {}, nodes.map((node) => nodeMark(node, positions.get(node.id), node.kind === "operator" || node.kind === "subagent" ? null : RADIUS[node.kind] + 9)));
    const pulseLayer = s("g", {});
    svg.append(edgeLayer, nodeLayer, pulseLayer);
    graphDom.pulses = pulseLayer;
    return svg;
  }

  function chord() {
    const nodes = state.graph.nodes.filter((node) => node.kind !== "subagent");
    const fresh = targets();
    const radius = 250;
    const step = (2 * Math.PI) / Math.max(nodes.length, 1);
    const spots = new Map(nodes.map((node) => {
      const angle = spotOf(node.id, fresh).chord;
      return [node.id, {x: radius * Math.cos(angle), y: radius * Math.sin(angle), angle}];
    }));
    const svg = chartFrame(450, "Chord: Nachrichten zwischen Agenten, Reihenfolge nach Nähe");
    const arcs = s("g", {});
    const point = (angle, r) => `${fixed(r * Math.cos(angle))},${fixed(r * Math.sin(angle))}`;
    for (const node of nodes) {
      const at = spots.get(node.id);
      const half = Math.min(step * 0.36, 0.5);
      arcs.append(s("path", {class: `group-arc k-${node.kind}`, d: `M${point(at.angle - half, radius + 14)} A${radius + 14},${radius + 14} 0 0 1 ${point(at.angle + half, radius + 14)}`}));
    }
    const pairs = new Map();
    const fans = new Map();
    for (const link of aggregate()) {
      const shade = tone(link.cls);
      if (!spots.has(link.source)) {
        continue;
      }
      if (link.target === "*") {
        const key = `${link.source}\u0000${shade}`;
        fans.set(key, {source: link.source, shade, count: (fans.has(key) ? fans.get(key).count : 0) + link.count});
        continue;
      }
      if (!spots.has(link.target) || link.target === link.source) {
        continue;
      }
      const [a, b] = [link.source, link.target].sort();
      const key = `${a}\u0000${b}\u0000${shade}`;
      pairs.set(key, {a, b, shade, count: (pairs.has(key) ? pairs.get(key).count : 0) + link.count});
    }
    const lanes = LEGEND.map(([name]) => name);
    for (const pair of pairs.values()) {
      const from = spots.get(pair.a);
      const to = spots.get(pair.b);
      const pull = 0.06 + 0.12 * lanes.indexOf(pair.shade);
      const control = {x: ((from.x + to.x) / 2) * pull, y: ((from.y + to.y) / 2) * pull};
      const start = toward(from, control, RADIUS.session + 2);
      const end = toward(to, control, RADIUS.session + 2);
      arcs.append(s("path", {class: `edge t-${pair.shade}`, d: `M${fixed(start.x)},${fixed(start.y)} Q${fixed(control.x)},${fixed(control.y)} ${fixed(end.x)},${fixed(end.y)}`, "stroke-width": fixed(width(pair.count))},
        s("title", {}, `${pair.a} ↔ ${pair.b}: ${pair.count}× ${LEGEND.find(([name]) => name === pair.shade)[1]}`)));
    }
    const offsets = new Map();
    for (const fan of fans.values()) {
      const at = spots.get(fan.source);
      const index = offsets.get(fan.source) || 0;
      offsets.set(fan.source, index + 1);
      const angle = at.angle + (index - 1) * 0.05;
      const length = Math.min(8 + 6 * Math.log2(1 + fan.count), 40);
      arcs.append(s("line", {class: `tick t-${fan.shade}`, x1: fixed((radius + 22) * Math.cos(angle)), y1: fixed((radius + 22) * Math.sin(angle)), x2: fixed((radius + 22 + length) * Math.cos(angle)), y2: fixed((radius + 22 + length) * Math.sin(angle)), "stroke-width": 4},
        s("title", {}, `${fan.source} an alle: ${fan.count}×`)));
    }
    svg.append(arcs, s("g", {}, nodes.map((node) => nodeMark(node, spots.get(node.id), 74))));
    return svg;
  }

  function swimlane() {
    const rank = new Map([HUMAN, ...state.graph.layout.order].map((id, index) => [id, index]));
    const lanes = state.graph.nodes.filter((node) => node.kind !== "subagent").sort((a, b) => (rank.has(a.id) ? rank.get(a.id) : 1e6) - (rank.has(b.id) ? rank.get(b.id) : 1e6));
    const begin = state.since;
    const end = Math.max(state.until, state.since + 1);
    const left = 160;
    const right = 24;
    const top = 40;
    const lane = 36;
    const full = 1120;
    const height = top + lanes.length * lane + 12;
    const x = (ts) => left + ((ts - begin) / (end - begin)) * (full - left - right);
    const y = new Map(lanes.map((node, index) => [node.id, top + index * lane + lane / 2]));
    const svg = s("svg", {viewBox: `0 0 ${full} ${height}`, class: "chart", role: "img", "aria-label": "Swimlane: Nachrichten über die Zeit"}, defs());
    lanes.forEach((node, index) => {
      svg.append(s("rect", {class: index % 2 ? "lane odd" : "lane", x: 0, y: top + index * lane, width: full, height: lane}));
      svg.append(s("text", {class: "lane-label", x: 14, y: top + index * lane + lane / 2, dy: "0.35em", "text-anchor": "start", on: {click: () => select(node.id)}}, node.label));
    });
    for (let index = 0; index <= 6; index += 1) {
      const ts = begin + ((end - begin) * index) / 6;
      svg.append(s("line", {class: "grid", x1: fixed(x(ts)), x2: fixed(x(ts)), y1: top - 6, y2: height - 8}));
      svg.append(s("text", {class: "axis", x: fixed(x(ts)), y: top - 14, "text-anchor": index === 0 ? "start" : index === 6 ? "end" : "middle"}, (end - begin > DAY ? absolute : clock).format(stampOf(ts))));
    }
    if (live()) {
      svg.append(s("line", {class: "now", x1: fixed(x(end)), x2: fixed(x(end)), y1: top - 6, y2: height - 8}));
    }
    const marks = s("g", {});
    const arrows = (cls, ts, from, to, words) => {
      const x0 = fixed(x(ts));
      const y0 = y.get(from);
      if (y0 === undefined) {
        return;
      }
      const shade = tone(cls);
      const hint = s("title", {}, `${clock.format(stampOf(ts))} · ${dash(labelOf(from))} → ${to.length ? to.map(labelOf).join(", ") : "alle"}\n${words}`);
      if (!to.length) {
        const rays = [[-6, -13], [0, -15], [6, -13], [-6, 13], [0, 15], [6, 13]].map(([dx, dy]) => `M${x0},${y0} l${dx},${dy}`).join(" ");
        marks.append(s("g", {class: `mark t-${shade}`}, hint, s("path", {d: rays}), s("circle", {cx: x0, cy: y0, r: 3.5})));
        return;
      }
      const bundle = s("g", {class: `mark t-${shade}`}, hint, s("circle", {cx: x0, cy: y0, r: 3}));
      for (const target of to) {
        const y1 = y.get(target);
        if (y1 !== undefined && y1 !== y0) {
          bundle.append(s("line", {x1: x0, y1: y0, x2: x0, y2: y1 > y0 ? y1 - 6 : y1 + 6, "marker-end": `url(#tip-${shade})`}));
        }
      }
      marks.append(bundle);
    };
    for (const row of state.radio) {
      arrows(row.class, row.ts, row.source, row.targets, row.text.length > 120 ? `${row.text.slice(0, 120)}…` : row.text);
    }
    for (const grant of state.grants) {
      arrows("grant", grant.ts, chairKey(), [grant.target], `Queue-Freigabe ${grant.kind} (${grant.id})`);
    }
    svg.append(marks);
    return svg;
  }

  function legend() {
    const axis = graph3d() ? space.views.graph.axis : "none";
    const words = {
      none: "Linienstärke = Anzahl · Nähe = Zusammenarbeit der letzten Zeit",
      time: "Weltlinie = Agent, Lage = Nähe der Zusammenarbeit zu ihrer Zeit · Bogen = ein Ereignis · Ebene = Stand der Wiedergabe",
      spawn: "Ebenen = Spawn-Tiefe · Bogen = Nachrichten im Zeitraum, Zahl im Stream",
    };
    return h("div", {class: "legend"}, LEGEND.map(([name, label]) => h("span", {}, h("i", {class: `swatch t-${name}`}), label)),
      axis === "none" ? null : h("span", {}, h("i", {class: "swatch t-spawn"}), "Spawn"),
      h("span", {class: "muted"}, words[axis]));
  }

  function side() {
    const node = state.graph.nodes.find((entry) => entry.id === ui.node);
    if (!node) {
      const where = graph3d() ? "eine Weltlinie oder darunter auf ihren Namen" : "einen Knoten";
      return [h("h2", {class: "panel-title"}, "Details"), h("p", {class: "muted"}, `Klicke auf ${where}: sein Panel zeigt Aufgaben, Claims, Subagenten und Verlauf.`)];
    }
    const messages = state.radio.filter((row) => row.source === node.id || row.targets.includes(node.id)).slice(-10).reverse();
    return [
      h("div", {class: "panel-head"},
        h("div", {}, h("h2", {class: "panel-title"}, node.label), h("span", {class: "muted"}, `${NODE_KINDS[node.kind]}${node.parent ? ` von ${labelOf(node.parent)}` : ""}`)),
        h("button", {type: "button", class: "btn small ghost", "aria-label": "Schließen", on: {click: () => select(node.id)}}, "×")),
      h("h3", {}, "Letzte Nachrichten", counter(messages.length)),
      messages.length ? h("ul", {class: "mini"}, messages.map((row) => h("li", {},
        h("div", {class: "row"}, klass(row.class), when(row.ts)),
        h("span", {class: "muted"}, `${dash(row.from)} → ${targetsOf(row)}`),
        h("span", {}, row.text)))) : h("p", {class: "muted"}, "Keine Nachrichten im gewählten Zeitraum."),
    ];
  }

  function graphScreen() {
    const stageBox = h("div", {class: "stage"});
    const aside = h("aside", {class: "card panel", "aria-live": "polite"});
    graphDom = {stage: stageBox, aside, pulses: null, space: null};
    return h("div", {class: "graph"},
      h("div", {class: "card controls"},
        h("div", {class: "segmented", role: "tablist", "aria-label": "Darstellung"}, GRAPHS.map(([id, name]) => h("button", {type: "button", role: "tab", "aria-selected": String(ui.graph === id), on: {click: () => go("graph", id)}}, name))),
        ui.graph === "orbit" ? spaceTools() : null),
      h("div", {class: "graph-body"}, h("div", {class: "card stage-card"}, stageBox, legend()), aside));
  }
