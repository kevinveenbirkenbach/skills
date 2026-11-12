  const spawn = {subs: new Map(), loading: false, dom: null};
  const SPAWN_KINDS = {operator: "bi-person-circle", chair: "bi-award", session: "bi-robot", subagent: "bi-cpu", twig: "bi-cpu"};

  function sessionRunning(node) {
    const life = (spawn.subs.get(node.id) || {}).data;
    if (life && life.died) {
      return false;
    }
    return node.claims.some((claim) => claim.beat !== null && claim.beat >= state.now - ACTIVE_BEAT);
  }

  function twigs(session) {
    const data = (spawn.subs.get(session) || {}).data;
    const rows = data ? data.subagents : [];
    const roots = [];
    const open = [];
    for (const row of rows) {
      const twig = {id: `${session}/${row.id}`, kind: "twig", label: `${row.type}: ${row.description}`, running: !row.finished, row, session, children: []};
      open.length = Math.min(open.length, Math.max(row.depth - 1, 0));
      (open.length ? open[open.length - 1].children : roots).push(twig);
      open.push(twig);
    }
    return roots;
  }

  function spawnTree() {
    const nodes = state.graph.nodes;
    const chair = nodes.find((node) => node.kind === "chair");
    const entry = (node) => ({
      id: node.id, kind: node.kind, label: node.label, node,
      running: node.kind === "operator" ? null : node.kind === "subagent" ? node.tasks.some((task) => task.status === "running") : sessionRunning(node),
      children: [],
    });
    const root = entry(nodes.find((node) => node.kind === "operator"));
    const byId = new Map([[root.id, root]]);
    if (chair) {
      byId.set(chair.id, entry(chair));
      root.children.push(byId.get(chair.id));
    }
    for (const node of nodes.filter((item) => item.kind === "session")) {
      byId.set(node.id, entry(node));
      (byId.get(chairKey()) || root).children.push(byId.get(node.id));
    }
    for (const node of nodes.filter((item) => item.kind === "subagent")) {
      (byId.get(node.parent) || byId.get(chairKey()) || root).children.push(entry(node));
    }
    for (const [id, held] of byId) {
      if (held.kind === "session" || held.kind === "chair") {
        held.children.push(...twigs(id));
      }
    }
    return root;
  }

  function spawnFlat(root) {
    const found = [];
    const walk = (entry, depth, parent) => {
      found.push({entry, depth, parent});
      entry.children.forEach((child) => walk(child, depth + 1, entry));
    };
    walk(root, 0, null);
    return found;
  }

  async function loadSpawn() {
    if (spawn.loading) {
      return;
    }
    const due = state.graph.nodes.filter((node) => (node.kind === "session" || node.kind === "chair") && SESSION_ID.test(node.id))
      .filter((node) => !spawn.subs.has(node.id) || Date.now() - spawn.subs.get(node.id).at > SUBS_TTL);
    if (!due.length) {
      return;
    }
    spawn.loading = true;
    await Promise.all(due.map(async (node) => {
      let data = null;
      try {
        const response = await fetch(`/api/subagents?session=${encodeURIComponent(node.id)}`, {cache: "no-store"});
        data = response.ok ? await response.json() : null;
      } catch {
        data = null;
      }
      spawn.subs.set(node.id, {at: Date.now(), data});
    }));
    spawn.loading = false;
    drawSpawn();
    stage();
  }

  function spawnItem(entry) {
    const running = entry.running === null ? null : entry.running ? chip("bi-play-circle", "running", "ok") : chip("bi-check-circle", "finished", "neutral");
    const open = entry.kind === "twig" ? () => focusSub(entry.session, entry.row.id) : entry.kind === "operator" ? null : () => select(entry.id);
    const name = open ? h("button", {type: "button", class: "linkish", title: entry.kind === "twig" ? "Show transcript in the stream" : `Open ${entry.label}`, "data-pick": entry.kind === "twig" ? null : entry.id, on: {click: open}}, entry.label) : h("strong", {}, entry.label);
    const meta = entry.kind === "twig" ? h("span", {class: "muted"}, `Depth ${entry.row.depth} · `, when(entry.row.started)) : h("span", {class: "muted"}, NODE_KINDS[entry.kind]);
    return h("li", {"data-kind": entry.kind, "data-running": entry.running === null ? null : String(entry.running)},
      h("div", {class: "spawn-row"}, h("span", {class: "state", role: "img", ...named(NODE_KINDS[entry.kind] || "Subagent")}, icon(SPAWN_KINDS[entry.kind])), name, entry.kind === "session" || entry.kind === "chair" ? presenceMark(entry.id, false) : null, running, meta),
      entry.children.length ? h("ul", {class: "spawn-tree"}, entry.children.map(spawnItem)) : null);
  }

  function spawnScreen() {
    const list = h("div", {class: "card spawn"});
    spawn.dom = {list};
    window.setTimeout(() => {
      drawSpawn();
      loadSpawn();
    }, 0);
    return list;
  }

  function drawSpawn() {
    if (!spawn.dom || !spawn.dom.list.isConnected) {
      spawn.dom = null;
      return;
    }
    const root = spawnTree();
    const all = spawnFlat(root).map(({entry}) => entry).filter((entry) => entry.running !== null);
    const running = all.filter((entry) => entry.running).length;
    spawn.dom.list.replaceChildren(
      h("div", {class: "inbox-head"}, h("h2", {class: "group-title"}, "Spawn tree", counter(all.length)), h("span", {class: "muted"}, `${running} running · ${all.length - running} finished · Operator → Chair → Sessions → Subagents`)),
      agentAncestry(root),
      h("ul", {class: "spawn-tree root"}, spawnItem(root)));
  }
