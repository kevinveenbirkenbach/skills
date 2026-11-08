  const LAYOUTS = [
    ["none", "Kraft", "bi-magnet", "Kräfte ordnen frei: Verbundenes zieht sich an, alles stößt sich ab"],
    ["time", "Zeit", "bi-clock", "Tiefe = Zeit: Früheres liegt hinten, Jüngeres vorn"],
    ["spawn", "Spawn-Tiefe", "bi-layers", "Tiefe = Spawn-Tiefe: jede Ebene eine Generation"],
  ];
  const KIND_COLORS = {operator: "accent", chair: "accent", session: "info", subagent: "violet", twig: "violet", repo: "warn", branch: "info", worktree: "teal", agent: "accent", artefact: "violet", task: "muted"};
  const LINK_COLORS = {spawn: "violet", contains: "line-strong", merge: "grant", overlap: "alarm", direct: "direct", broadcast: "broadcast", alarm: "alarm", security: "security", grant: "grant"};
  const SPAWNED = new Set(["twig", "subagent"]);
  const DEPTH_GAP = 90;
  const TIME_DEPTH = 640;
  const g3 = {lib: null, three: null, graph: null, host: null, tab: "", sig: "", planes: [], colors: null, failed: ""};

  const layoutOf = () => space.views.graph.axis;

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = src;
      tag.nonce = NONCE;
      tag.async = true;
      tag.addEventListener("load", resolve);
      tag.addEventListener("error", () => reject(new Error(`${src} nicht geladen`)));
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
    const group = h("div", {class: "segmented", role: "group", "aria-label": "Anordnung"}, LAYOUTS.map(([id, label, name, hint]) => h("button", {
      type: "button", class: "icon-only", "data-layout": id, ...named(label, `${label}: ${hint}`), "aria-pressed": String(layoutOf() === id), on: {click: () => chooseLayout(tab, id, group)},
    }, icon(name))));
    return h("div", {class: "space-tools"}, group,
      iconBtn("bi-arrow-counterclockwise", "Ansicht zurücksetzen", "btn small ghost", () => g3.graph && g3.graph.zoomToFit(calm.matches ? 0 : 600, 40)),
      h("span", {class: "muted"}, "Ziehen dreht · rechts ziehen verschiebt · Rad zoomt · Klick öffnet das Panel"));
  }

  function chooseLayout(tab, id, group) {
    for (const button of group.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.layout === id));
    }
    if (id !== layoutOf()) {
      setView("graph", {...space.views.graph, axis: id}, false);
      g3.sig = "";
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

  function colors3d() {
    const css = window.getComputedStyle(document.documentElement);
    const value = (name) => css.getPropertyValue(`--${name}`).trim() || "#888";
    const roles = new Set([...Object.values(KIND_COLORS), ...Object.values(LINK_COLORS), "text"]);
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
    if (tab === "artifacts") {
      artSelect(node.id);
    } else if (node.kind === "twig") {
      focusSub(node.session, node.sub);
    } else {
      select(node.id);
    }
  }

  function list3d(tab, data) {
    const pickable = data.nodes.filter((node) => node.kind !== "operator");
    return h("details", {class: "space-list"}, h("summary", {}, `${pickable.length} Knoten als Liste`),
      h("div", {class: "chips", role: "group", "aria-label": "Knoten"}, pickable.slice(0, 400).map((node) => h("button", {type: "button", class: "chip", title: node.label, "data-node": node.id, on: {click: () => pick3d(tab, node)}}, node.label))));
  }

  function signature3d(tab, data) {
    return JSON.stringify([tab, layoutOf(), data.nodes.map((node) => [node.id, node.kind, node.depth, node.ts]), data.links.map((link) => [link.source, link.target, link.kind])]);
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
      return;
    }
    if (g3.host !== host) {
      dispose3d();
      g3.host = host;
      g3.tab = tab;
      host.replaceChildren(h("div", {class: "graph3d", role: "img", "aria-label": `3D-Graph ${tab === "agents" ? "der Agenten" : "der Artefakte"}; die Knoten stehen auch darunter als Liste`}), h("div", {class: "space-note"}, "Lade 3D …"));
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
      host.replaceChildren(emptyState("3D nicht geladen", g3.failed || "3d-force-graph fehlt."));
      return;
    }
    if (!g3.graph) {
      try {
        g3.graph = Graph({controlType: "orbit"})(box);
      } catch (error) {
        host.replaceChildren(emptyState("3D nicht verfügbar", `Dieser Browser gibt kein WebGL: ${error.message || error}`));
        g3.host = null;
        return;
      }
      const colors = colors3d();
      g3.graph.backgroundColor("rgba(0,0,0,0)").showNavInfo(false).nodeRelSize(5).nodeOpacity(0.92).linkOpacity(0.45)
        .nodeLabel((node) => h("span", {}, node.label)).nodeVal((node) => ({operator: 6, chair: 4, repo: 6, branch: 3, session: 2.5}[node.kind] || 1))
        .nodeColor((node) => g3.colors[KIND_COLORS[node.kind]] || colors.text).linkColor((link) => g3.colors[LINK_COLORS[link.kind]] || colors.text)
        .linkWidth((link) => (link.kind === "contains" || link.kind === "spawn" ? 0.6 : Math.min(0.8 + Math.log2(1 + (link.count || 1)), 4)))
        .onNodeClick((node) => pick3d(g3.tab, node)).onEngineStop(() => g3.graph && g3.graph.zoomToFit(calm.matches ? 0 : 400, 40));
      g3.graph.warmupTicks(calm.matches ? 160 : 80);
      if (calm.matches) {
        g3.graph.cooldownTicks(0);
      } else {
        g3.graph.cooldownTime(4000);
      }
    }
    const layout = layoutOf();
    place(data.nodes, layout);
    g3.graph.width(box.clientWidth).height(box.clientHeight).graphData(data);
    drawPlanes(layout, data.nodes);
    const words = `${data.nodes.length} Knoten · ${data.links.length} Kanten · ${LAYOUTS.find(([id]) => id === layout)[1]}${calm.matches ? " · ohne Bewegung (prefers-reduced-motion)" : ""}`;
    host.replaceChildren(box, h("div", {class: "space-note"}, words), list3d(tab, data));
    window.requestAnimationFrame(() => g3.graph && g3.host === host && g3.graph.zoomToFit(0, 40));
  }

  function dispose3d() {
    if (g3.graph) {
      g3.graph.pauseAnimation();
      if (typeof g3.graph._destructor === "function") {
        g3.graph._destructor();
      }
    }
    g3.graph = null;
    g3.host = null;
    g3.sig = "";
    g3.planes = [];
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
