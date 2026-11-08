  function aggregate() {
    const links = new Map();
    const add = (source, target, cls) => {
      const key = `${source}\u0000${target}\u0000${cls}`;
      const link = links.get(key) || {source, target, cls, count: 0};
      link.count += 1;
      links.set(key, link);
    };
    for (const row of state.radio) {
      for (const target of row.source ? (row.targets.length ? row.targets : ["*"]) : []) {
        add(row.source, target, row.class);
      }
    }
    for (const grant of state.grants) {
      add(chairKey(), grant.target, "grant");
    }
    const order = (link) => (tone(link.cls) === "alarm" ? 1e6 : 0) + link.count;
    return [...links.values()].sort((a, b) => order(a) - order(b));
  }

  const width = (count) => Math.min(1.25 + Math.log2(1 + count) * 1.6, 9);
  const tone = (cls) => Space.TONES[cls] || "direct";

  function defs() {
    return s("defs", {}, LEGEND.map(([name]) => s("marker", {id: `tip-${name}`, viewBox: "0 0 10 10", refX: 8, refY: 5, markerWidth: 9, markerHeight: 9, markerUnits: "userSpaceOnUse", orient: "auto-start-reverse", class: `t-${name}`},
      s("path", {class: "tip", d: "M0,0 L10,5 L0,10 z"}))));
  }

  function toward(point, aim, gap) {
    const dx = aim.x - point.x;
    const dy = aim.y - point.y;
    const length = Math.hypot(dx, dy) || 1;
    return {x: point.x + (dx / length) * gap, y: point.y + (dy / length) * gap};
  }

  function radiusOf(id) {
    const node = state.graph.nodes.find((entry) => entry.id === id);
    return node ? RADIUS[node.kind] : RADIUS.session;
  }

  function targets() {
    const plan = state.graph.layout;
    const order = [HUMAN, ...plan.order];
    return new Map(order.map((id, index) => {
      const spot = plan.orbit[id] || {angle: -Math.PI / 2, radius: 0};
      return [id, {angle: spot.angle, radius: spot.radius, chord: -Math.PI / 2 + (2 * Math.PI * index) / order.length}];
    }));
  }

  function step(now) {
    const progress = motion.duration ? Math.min((now - motion.start) / motion.duration, 1) : 1;
    const eased = Space.ease(progress);
    motion.current = new Map([...motion.target].map(([id, to]) => {
      const from = motion.from.get(id) || to;
      return [id, {angle: Space.turn(from.angle, to.angle, eased), radius: from.radius + (to.radius - from.radius) * eased, chord: Space.turn(from.chord, to.chord, eased)}];
    }));
    if (ui.views.agents !== "swimlane") {
      stage();
    }
    motion.frame = progress < 1 ? window.requestAnimationFrame(step) : 0;
  }

  function relayout(duration) {
    const next = targets();
    motion.from = new Map([...next.keys()].map((id) => [id, motion.current.get(id) || next.get(id)]));
    motion.target = next;
    motion.start = performance.now();
    motion.duration = calm.matches ? 0 : duration;
    if (!motion.frame) {
      motion.frame = window.requestAnimationFrame(step);
    }
  }

  function spotOf(id, fresh) {
    return motion.current.get(id) || fresh.get(id) || {angle: -Math.PI / 2, radius: RINGS[1], chord: -Math.PI / 2};
  }

  function layout(nodes) {
    const fresh = targets();
    const spots = new Map();
    for (const node of nodes.filter((entry) => entry.kind !== "subagent")) {
      const at = spotOf(node.id, fresh);
      const radius = node.kind === "operator" ? 0 : at.radius;
      spots.set(node.id, {x: radius * Math.cos(at.angle), y: radius * Math.sin(at.angle), angle: at.angle});
    }
    const moons = new Map();
    for (const node of nodes.filter((entry) => entry.kind === "subagent")) {
      moons.set(node.parent, [...(moons.get(node.parent) || []), node]);
    }
    for (const [parent, list] of moons) {
      const base = spots.get(parent) || spots.get(chairKey()) || {x: 0, y: 0, angle: -Math.PI / 2};
      list.forEach((node, index) => spots.set(node.id, Space.moon(base, index, list.length)));
    }
    return spots;
  }

  function caption(node, at, r, gap) {
    if (node.kind === "subagent") {
      return null;
    }
    if (gap === null) {
      return s("text", {class: "label", y: r + 17, "text-anchor": "middle"}, node.label);
    }
    const cos = Math.cos(at.angle);
    const sin = Math.sin(at.angle);
    const anchor = cos > 0.3 ? "start" : cos < -0.3 ? "end" : "middle";
    return s("text", {class: "label", x: fixed(cos * gap), y: fixed(sin * (gap + 3)), dy: "0.35em", "text-anchor": anchor}, node.label);
  }

  function select(id) {
    ui.node = ui.node === id ? null : id;
    stage();
    drawSide();
    const node = state.graph.nodes.find((entry) => entry.id === id);
    if (ui.node !== null && node && node.kind !== "operator") {
      openAgent(node.kind === "subagent" ? node.parent : id);
    }
  }

  function nodeMark(node, at, gap) {
    const r = RADIUS[node.kind];
    const classes = ["node", `k-${node.kind}`, ui.node === node.id ? "selected" : "", node.claims.length ? "claimed" : "", speech.current && speech.current.who === node.id ? "speaking" : ""].filter(Boolean).join(" ");
    const tasks = node.tasks.length ? ` · ${node.tasks.length} tasks` : "";
    return s("g", {
      class: classes, transform: `translate(${fixed(at.x)} ${fixed(at.y)})`, tabindex: 0, role: "button", "aria-label": `${node.label}, ${NODE_KINDS[node.kind]}`,
      on: {
        click: () => select(node.id),
        keydown: (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            select(node.id);
          }
        },
      },
    },
    s("title", {}, `${node.label} · ${NODE_KINDS[node.kind]}${node.parent ? ` of ${labelOf(node.parent)}` : ""}${tasks}`),
    s("circle", {r}),
    node.kind === "subagent" ? null : s("text", {class: "initial", "text-anchor": "middle", dy: "0.35em"}, node.label.slice(0, 1).toUpperCase()),
    caption(node, at, r, gap));
  }

  function chartFrame(size, label) {
    return s("svg", {viewBox: `${-size} ${-size} ${2 * size} ${2 * size}`, class: "chart", role: "img", "aria-label": label}, defs());
  }
