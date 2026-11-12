  const LAYOUTS = [
    ["none", "Force", "bi-magnet", "Forces arrange freely: linked nodes attract, everything repels"],
    ["time", "Time", "bi-clock", "Depth = time: earlier lies behind, later in front"],
    ["spawn", "Spawn depth", "bi-layers", "Depth = spawn depth: each level one generation"],
  ];
  const KIND_COLORS = {operator: "accent", chair: "accent", session: "info", subagent: "violet", twig: "violet", repo: "warn", branch: "info", worktree: "teal", agent: "accent", artefact: "violet", task: "muted"};
  const LINK_COLORS = {spawn: "violet", contains: "line-strong", merge: "grant", overlap: "alarm", direct: "direct", broadcast: "broadcast", alarm: "alarm", security: "security", grant: "grant", after: "violet", base: "info", queue: "warn"};
  const TONE_ROLES = {ok: "ok", bad: "bad", info: "info", warn: "warn", neutral: "muted"};
  const DEPENDENCIES = new Set(["after", "base", "queue"]);
  const SPAWNED = new Set(["twig", "subagent"]);
  const DEPTH_GAP = 90;
  const TIME_DEPTH = 640;
  const TOP = {operator: 6, chair: 4, session: 2.5};
  const g3 = {lib: null, three: null, THREE: null, graph: null, host: null, tab: "", sig: "", planes: [], colors: null, failed: "", picked: null, fit: false, badges: new Map(), faces: new Set(), textures: new Map(), pulse: 0};

  const layoutsOf = (tab) => (tab === "tasks" ? LAYOUTS.filter(([id]) => id !== "spawn") : LAYOUTS);
  const layoutOf = (tab) => (layoutsOf(tab).some(([id]) => id === space.views.graph.axis) ? space.views.graph.axis : "none");

  function fit3d(ms) {
    if (g3.graph) {
      g3.graph.zoomToFit(ms, 40);
    }
  }

  function builtFit() {
    if (g3.fit) {
      g3.fit = false;
      fit3d(calm.matches ? 0 : 400);
    }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = src;
      tag.nonce = NONCE;
      tag.async = true;
      tag.addEventListener("load", resolve);
      tag.addEventListener("error", () => reject(new Error(`${src} not loaded`)));
      document.head.append(tag);
    });
  }

  function forceGraph() {
    if (!g3.lib) {
      g3.lib = loadScript("/vendor/3d-force-graph.min.js").then(() => window.ForceGraph3D);
    }
    return g3.lib;
  }

  function threeModule() {
    if (!g3.three) {
      g3.three = import("/vendor/three.module.js").catch(() => null);
    }
    return g3.three;
  }

  function layoutTools(tab) {
    const group = h("div", {class: "segmented", role: "group", "aria-label": "Layout"}, layoutsOf(tab).map(([id, label, name, hint]) => h("button", {
      type: "button", class: "icon-only", "data-layout": id, ...named(label, `${label}: ${tab === "tasks" && id === "time" ? "depth = start: earlier lies behind, later in front, forecasts behind their predecessors" : hint}`), "aria-pressed": String(layoutOf(tab) === id), on: {click: () => chooseLayout(tab, id, group)},
    }, icon(name))));
    return h("div", {class: "space-tools"}, group,
      iconBtn("bi-arrow-counterclockwise", "Reset view", "btn small ghost", () => fit3d(calm.matches ? 0 : 600)),
      h("span", {class: "muted"}, "Drag turns · right drag pans · wheel zooms · click opens the popup"),
      nodeSearch(() => model3d(tab).nodes, (node) => pick3d(tab, node)));
  }

  function chooseLayout(tab, id, group) {
    for (const button of group.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.layout === id));
    }
    if (id !== layoutOf(tab)) {
      setView("graph", {...space.views.graph, axis: id}, false);
      g3.sig = "";
      g3.fit = true;
      if (ui.screen === tab) {
        stage3d(tab, g3.host);
      }
    }
  }

  function agentModel() {
    const depthOf = {operator: 0, chair: 1, session: 2, subagent: 3};
    const born = (node) => ((spawn.subs.get(node.id) || {}).data || {}).since;
    const nodes = state.graph.nodes.map((node) => ({
      id: node.id, kind: node.kind, label: node.label, depth: depthOf[node.kind], ts: born(node) || (node.timeline[0] || {}).since || state.since,
      parent: node.kind === "operator" ? null : node.kind === "chair" ? HUMAN : node.kind === "session" ? chairKey() : node.parent || chairKey(),
      face: look.faces && Object.hasOwn(TOP, node.kind), badge: node.kind === "chair" || node.kind === "session",
    }));
    for (const node of state.graph.nodes.filter((entry) => entry.kind === "session" || entry.kind === "chair")) {
      const walk = (twig, parent, depth) => {
        nodes.push({id: twig.id, kind: "twig", label: twig.label, depth, ts: twig.row.since || twig.row.started, parent, session: twig.session, sub: twig.row.id});
        twig.children.forEach((child) => walk(child, twig.id, depth + 1));
      };
      twigs(node.id).forEach((twig) => walk(twig, node.id, depthOf[node.kind] + 1));
    }
    const ids = new Set(nodes.map((node) => node.id));
    const links = nodes.filter((node) => node.parent && ids.has(node.parent)).map((node) => ({source: node.parent, target: node.id, kind: "spawn"}));
    for (const link of aggregate().filter((entry) => entry.target !== "*" && ids.has(entry.source) && ids.has(entry.target) && entry.source !== entry.target)) {
      links.push({source: link.source, target: link.target, kind: tone(link.cls), count: link.count});
    }
    return {nodes: SpaceView.notBeforeParent(nodes, SPAWNED), links};
  }

  function model3d(tab) {
    if (tab === "agents") {
      return agentModel();
    }
    if (tab === "tasks") {
      return taskModel3d();
    }
    const built = tree.model || {nodes: [], links: []};
    return {nodes: built.nodes.map((node) => ({id: node.id, kind: node.kind, label: node.label, depth: node.depth, ts: node.ts, parent: node.parent})), links: built.links.map((link) => ({...link}))};
  }

  function place(nodes, layout) {
    const times = nodes.map((node) => node.ts).filter(Number.isFinite);
    const [low, high] = [Math.min(...times), Math.max(...times)];
    const span = high - low;
    for (const node of nodes) {
      if (layout === "spawn") {
        node.fz = -node.depth * DEPTH_GAP;
      } else if (layout === "time") {
        node.fz = span > 0 && Number.isFinite(node.ts) ? ((node.ts - low) / span - 0.5) * TIME_DEPTH : 0;
      } else {
        delete node.fz;
      }
    }
  }

  function keepPlaces(nodes) {
    const laid = new Map(g3.graph.graphData().nodes.filter((node) => Number.isFinite(node.x)).map((node) => [node.id, node]));
    for (const node of nodes) {
      const old = laid.get(node.id);
      if (old) {
        Object.assign(node, {x: old.x, y: old.y, z: old.z});
      }
    }
  }

  function colors3d() {
    const css = window.getComputedStyle(document.documentElement);
    const value = (name) => css.getPropertyValue(`--${name}`).trim() || "#888";
    const roles = new Set([...Object.values(KIND_COLORS), ...Object.values(LINK_COLORS), ...Object.values(TONE_ROLES), "text", "alarm"]);
    g3.colors = Object.fromEntries([...roles].map((role) => [role, value(role)]));
    return g3.colors;
  }

  async function drawPlanes(layout, nodes) {
    const graph = g3.graph;
    const scene = graph.scene();
    for (const plane of g3.planes) {
      scene.remove(plane);
    }
    g3.planes = [];
    if (layout === "none") {
      return;
    }
    const THREE = await threeModule();
    if (!THREE || g3.graph !== graph) {
      return;
    }
    const levels = [...new Set(nodes.map((node) => node.fz))].filter(Number.isFinite).sort((a, b) => a - b);
    const shown = layout === "spawn" ? levels : [levels[0], levels[levels.length - 1]].filter(Number.isFinite);
    for (const z of new Set(shown)) {
      const grid = new THREE.GridHelper(520, 8, g3.colors["line-strong"], g3.colors["line-strong"]);
      grid.rotation.x = Math.PI / 2;
      grid.position.z = z;
      grid.material.transparent = true;
      grid.material.opacity = 0.18;
      scene.add(grid);
      g3.planes.push(grid);
    }
  }

  function pick3d(tab, node) {
    if (node.kind === "twig") {
      focusSub(node.session, node.sub);
      return;
    }
    ({artifacts: artSelect, tasks: taskSelect}[tab] || select)(node.id, anchor3d(node.id), () => mark3d(null));
    mark3d(node.id);
  }

  function anchor3d(id) {
    return () => {
      const node = g3.graph && g3.host && g3.host.isConnected ? g3.graph.graphData().nodes.find((entry) => entry.id === id) : null;
      if (!node || !Number.isFinite(node.x)) {
        return null;
      }
      const at = g3.graph.graph2ScreenCoords(node.x, node.y, node.z);
      const box = g3.host.querySelector(".graph3d").getBoundingClientRect();
      return {left: box.left + at.x - 8, top: box.top + at.y - 8, width: 16, height: 16};
    };
  }

  function mark3d(id) {
    g3.picked = id;
    if (g3.graph) {
      g3.graph.nodeColor(g3.graph.nodeColor()).nodeVal(g3.graph.nodeVal());
    }
    const box = g3.host && g3.host.querySelector(".graph3d");
    if (box && id) {
      box.dataset.picked = id;
    } else if (box) {
      delete box.dataset.picked;
    }
  }

  function signature3d(tab, data) {
    return JSON.stringify([tab, layoutOf(tab), data.nodes.map((node) => [node.id, node.kind, node.depth, node.ts, node.tone, node.face]), data.links.map((link) => [link.source, link.target, link.kind])]);
  }

  function canvasTexture(size, paint) {
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    paint(canvas.getContext("2d"));
    const texture = new g3.THREE.CanvasTexture(canvas);
    texture.colorSpace = g3.THREE.SRGBColorSpace;
    return texture;
  }

  function cached(key, make) {
    if (!g3.textures.has(key)) {
      g3.textures.set(key, make());
    }
    return g3.textures.get(key);
  }

  function paintFace(context, key) {
    context.scale(128 / Faces.SIZE, 128 / Faces.SIZE);
    for (const [tag, part] of Faces.of(key).parts) {
      const path = tag === "path" ? new Path2D(part.d) : new Path2D();
      if (tag === "ellipse") {
        path.ellipse(part.cx, part.cy, part.rx, part.ry, 0, 0, 2 * Math.PI);
      } else if (tag === "rect") {
        path.roundRect(part.x, part.y, part.width, part.height, part.rx || 0);
      }
      context.globalAlpha = part.opacity ?? 1;
      if (part.fill && part.fill !== "none") {
        context.fillStyle = part.fill;
        context.fill(path);
      }
      if (part.stroke) {
        context.globalAlpha *= part["stroke-opacity"] ?? 1;
        context.strokeStyle = part.stroke;
        context.lineWidth = part["stroke-width"] || 1;
        context.lineCap = part["stroke-linecap"] || "butt";
        context.lineJoin = part["stroke-linejoin"] || "miter";
        context.stroke(path);
      }
    }
  }

  function badgeTexture(value) {
    const [, name, tone] = PRESENCE[value];
    const color = g3.colors[tone] || g3.colors.text;
    return cached(`${value}:${color}`, () => canvasTexture(64, (context) => {
      context.fillStyle = "rgba(255, 255, 255, 0.92)";
      context.arc(32, 32, 31, 0, 2 * Math.PI);
      context.fill();
      context.fillStyle = color;
      context.translate(12, 12);
      context.scale(2.5, 2.5);
      for (const path of document.querySelectorAll(`#${name} path`)) {
        context.fill(new Path2D(path.getAttribute("d")), path.getAttribute("fill-rule") || "nonzero");
      }
    }));
  }

  function count3d() {
    const box = g3.host && g3.host.querySelector(".graph3d");
    if (box) {
      box.dataset.faces = String(g3.faces.size);
      box.dataset.badges = String([...g3.badges.values()].filter((badge) => badge.visible).length);
    }
    if (!g3.pulse && g3.badges.size && !calm.matches) {
      g3.pulse = window.requestAnimationFrame(pulse3d);
    }
  }

  function paintBadge(key, badge) {
    const value = presenceOf(key);
    badge.visible = value !== null;
    badge.userData.state = value;
    const map = value ? badgeTexture(value) : null;
    if (map && badge.material.map !== map) {
      badge.material.map = map;
      badge.material.needsUpdate = true;
    }
  }

  function badges3d() {
    for (const [key, badge] of g3.badges) {
      paintBadge(key, badge);
    }
    count3d();
  }

  function pulse3d(now) {
    g3.pulse = 0;
    if (!g3.graph || !g3.badges.size || calm.matches) {
      return;
    }
    for (const badge of g3.badges.values()) {
      const {state: value, size} = badge.userData;
      const beat = value === "alive" ? 1 + 0.2 * Math.max(0, Math.sin(now / 150)) : 1;
      badge.scale.set(size * beat, size * beat, 1);
      badge.material.rotation = value === "working" ? now / 500 : value === "suspending" ? Math.PI * (Math.floor(now / 1200) % 2) : 0;
      badge.material.opacity = ["sleeping", "dead", "unreachable"].includes(value) ? 0.6 + 0.4 * Math.cos(now / (value === "unreachable" ? 200 : 900)) ** 2 : 1;
    }
    g3.pulse = window.requestAnimationFrame(pulse3d);
  }

  function object3d(node) {
    const THREE = g3.THREE;
    if (!THREE || !(node.face || node.badge)) {
      return null;
    }
    const radius = Math.cbrt(TOP[node.kind]) * 5;
    const group = new THREE.Group();
    if (node.face) {
      const face = new THREE.Sprite(new THREE.SpriteMaterial({map: cached(`face:${node.id}`, () => canvasTexture(128, (context) => paintFace(context, node.id)))}));
      face.scale.set(radius * 2.4, radius * 2.4, 1);
      group.add(face);
      g3.faces.add(node.id);
    }
    if (node.badge) {
      const badge = new THREE.Sprite(new THREE.SpriteMaterial());
      badge.userData.size = radius * 1.1;
      badge.scale.set(badge.userData.size, badge.userData.size, 1);
      badge.position.set(0, radius * 1.7, 0);
      paintBadge(node.id, badge);
      g3.badges.set(node.id, badge);
      group.add(badge);
    }
    count3d();
    return group;
  }

  async function stage3d(tab, host) {
    if (!host) {
      return;
    }
    if (tab === "agents") {
      loadSpawn();
    }
    const data = model3d(tab);
    const sig = signature3d(tab, data);
    if (g3.host === host && g3.sig === sig) {
      badges3d();
      return;
    }
    if (g3.host !== host) {
      dispose3d();
      g3.host = host;
      g3.tab = tab;
      host.replaceChildren(h("div", {class: "graph3d", role: "img", "aria-label": `3D graph of the ${tab}; the search above finds every node`}), h("div", {class: "space-note"}, "Loading 3D …"));
    }
    g3.sig = sig;
    const box = host.querySelector(".graph3d");
    let Graph = null;
    try {
      Graph = await forceGraph();
    } catch (error) {
      g3.failed = String(error.message || error);
    }
    if (g3.host !== host) {
      return;
    }
    if (!Graph) {
      host.replaceChildren(emptyState("3D not loaded", g3.failed || "3d-force-graph is missing."));
      return;
    }
    if (tab === "agents" && !g3.THREE) {
      g3.THREE = await threeModule();
      if (g3.host !== host) {
        return;
      }
    }
    if (!g3.graph) {
      try {
        g3.graph = Graph({controlType: "orbit"})(box);
      } catch (error) {
        host.replaceChildren(emptyState("3D unavailable", `This browser offers no WebGL: ${error.message || error}`));
        g3.host = null;
        return;
      }
      const colors = colors3d();
      g3.graph.backgroundColor("rgba(0,0,0,0)").showNavInfo(false).nodeRelSize(5).nodeOpacity(0.92).linkOpacity(0.45)
        .nodeLabel((node) => h("span", {}, node.label)).nodeVal((node) => ({operator: 6, chair: 4, repo: 6, branch: 3, session: 2.5}[node.kind] || 1) * (node.id === g3.picked ? 4 : 1))
        .nodeColor((node) => (node.id === g3.picked ? g3.colors.alarm : g3.colors[node.tone || KIND_COLORS[node.kind]] || colors.text)).linkColor((link) => g3.colors[LINK_COLORS[link.kind]] || colors.text)
        .linkWidth((link) => (link.kind === "contains" || link.kind === "spawn" ? 0.6 : Math.min(0.8 + Math.log2(1 + (link.count || 1)), 4)))
        .linkDirectionalArrowLength((link) => (DEPENDENCIES.has(link.kind) ? 5 : 0)).linkDirectionalArrowRelPos(1)
        .nodeThreeObject(object3d).nodeThreeObjectExtend((node) => !node.face)
        .onNodeClick((node) => pick3d(g3.tab, node)).onEngineStop(builtFit);
      g3.fit = true;
      g3.graph.warmupTicks(calm.matches ? 160 : 80);
      if (calm.matches) {
        g3.graph.cooldownTicks(0);
      } else {
        g3.graph.cooldownTime(4000);
      }
    }
    const layout = layoutOf(tab);
    keepPlaces(data.nodes);
    place(data.nodes, layout);
    g3.badges = new Map();
    g3.faces = new Set();
    g3.graph.width(box.clientWidth).height(box.clientHeight).graphData(data);
    drawPlanes(layout, data.nodes);
    const words = `${data.nodes.length} nodes · ${data.links.length} edges · ${LAYOUTS.find(([id]) => id === layout)[1]}${calm.matches ? " · without motion (prefers-reduced-motion)" : ""}`;
    host.replaceChildren(box, h("div", {class: "space-note"}, words));
    window.requestAnimationFrame(() => g3.host === host && g3.fit && fit3d(0));
  }

  function dispose3d() {
    if (g3.graph) {
      g3.graph.pauseAnimation();
      if (typeof g3.graph._destructor === "function") {
        g3.graph._destructor();
      }
    }
    window.cancelAnimationFrame(g3.pulse);
    g3.pulse = 0;
    g3.graph = null;
    g3.host = null;
    g3.sig = "";
    g3.planes = [];
    g3.badges = new Map();
    g3.faces = new Set();
  }

  function refresh3d() {
    if (!g3.graph || !g3.host) {
      return;
    }
    if (!g3.host.isConnected) {
      dispose3d();
      return;
    }
    colors3d();
    const box = g3.host.querySelector(".graph3d");
    g3.graph.width(box.clientWidth).height(box.clientHeight).nodeColor(g3.graph.nodeColor()).linkColor(g3.graph.linkColor());
  }
