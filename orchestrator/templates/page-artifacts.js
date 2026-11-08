  const art = {repo: "", node: null};
  const ART_KINDS = {repo: ["Repository", "bi-git"], branch: ["Branch", "bi-diagram-2"], worktree: ["Worktree", "bi-folder2-open"], agent: ["Agent", "bi-robot"], artefact: ["Artifact", "bi-box-seam"], task: ["Task", "bi-card-checklist"]};
  const ARTEFACT_ICONS = {image: "bi-box-seam", volume: "bi-hdd", log: "bi-file-text", dir: "bi-folder"};
  const LANE_MARKS = {commit: ["Commit", "bi-record-circle"], review: ["Review", "bi-eye"], gate: ["Gate", "bi-shield-check"], push: ["Push", "bi-cloud-upload"]};
  const tail = (path, parts) => String(path).split("/").filter(Boolean).slice(-parts).join("/");
  const epochOf = (text) => {
    const value = Date.parse(text);
    return Number.isFinite(value) ? value / 1000 : null;
  };

  function artifactModel(data) {
    const nodes = [];
    const links = [];
    const add = (node) => {
      nodes.push(node);
      if (node.parent) {
        links.push({source: node.parent, target: node.id, kind: "contains"});
      }
      return node.id;
    };
    const leaves = (holder, wt, depth) => {
      for (const name of wt.workers || []) {
        add({id: `agent:${name}@${wt.path}`, kind: "agent", label: name, depth, ts: holder.ts, parent: holder.id, data: {name}, repo: holder.repo});
      }
      for (const found of wt.artefacts || []) {
        add({id: `artefact:${holder.id}\u0000${found.task}\u0000${found.ref}`, kind: "artefact", label: found.name, depth, ts: epochOf(found.added) || holder.ts, parent: holder.id, data: found, repo: holder.repo});
      }
    };
    for (const repo of data.repos || []) {
      const base = epochOf(repo.scanned_at) || data.scanned || nowSeconds();
      const rid = add({id: `repo:${repo.path}`, kind: "repo", label: repo.name, depth: 0, ts: base, parent: null, data: repo, repo: repo.path});
      for (const branch of repo.branches) {
        const last = branch.events && branch.events.length ? branch.events[branch.events.length - 1].ts : base;
        const bid = add({id: `branch:${repo.path}\u0000${branch.name}`, kind: "branch", label: branch.name, depth: 1, ts: last, parent: rid, data: branch, repo: repo.path});
        for (const wt of branch.worktrees) {
          const holder = {id: `wt:${wt.path}`, kind: "worktree", label: tail(wt.path, 2), depth: 2, ts: last, parent: bid, data: {...wt, branch: branch.name}, repo: repo.path};
          add(holder);
          leaves(holder, wt, 3);
        }
      }
      for (const wt of repo.detached) {
        const holder = {id: `wt:${wt.path}`, kind: "worktree", label: tail(wt.path, 2), depth: 1, ts: base, parent: rid, data: {...wt, branch: ""}, repo: repo.path};
        add(holder);
        leaves(holder, wt, 2);
      }
      for (const merge of repo.merges || []) {
        links.push({source: `branch:${repo.path}\u0000${merge.from}`, target: `branch:${repo.path}\u0000${merge.into}`, kind: "merge", by: merge.by});
      }
      for (const overlap of repo.overlaps || []) {
        links.push({source: `branch:${repo.path}\u0000${overlap.a}`, target: `branch:${repo.path}\u0000${overlap.b}`, kind: "overlap", count: overlap.count});
      }
      for (const edge of flowEdges(repo)) {
        links.push({source: `branch:${repo.path}\u0000${edge.from}`, target: `branch:${repo.path}\u0000${edge.into}`, kind: "flow", side: edge.side});
      }
    }
    for (const task of data.tasks || []) {
      const tid = add({id: `task:${task.task}`, kind: "task", label: task.task, depth: 0, ts: nowSeconds(), parent: null, data: task, repo: ""});
      for (const found of task.artefacts) {
        add({id: `artefact:${tid}\u0000${found.task}\u0000${found.ref}`, kind: "artefact", label: found.name, depth: 1, ts: epochOf(found.added) || nowSeconds(), parent: tid, data: found, repo: ""});
      }
    }
    const ids = new Set(nodes.map((node) => node.id));
    return {nodes, links: links.filter((link) => ids.has(link.source) && ids.has(link.target)), byId: new Map(nodes.map((node) => [node.id, node]))};
  }

  function chosenRepo() {
    const repos = tree.data && !tree.data.error ? tree.data.repos : [];
    const weight = (repo) => repo.branches.length + repo.branches.reduce((sum, entry) => sum + entry.worktrees.length, 0);
    const found = repos.find((repo) => repo.path === art.repo) || [...repos].sort((a, b) => weight(b) - weight(a))[0] || null;
    art.repo = found ? found.path : "";
    return found;
  }

  function artSelect(id) {
    art.node = art.node === id ? null : id;
    drawArtifacts();
  }

  function artMark(node, at, radius, extra, caption) {
    const [kindName] = ART_KINDS[node.kind];
    const classes = ["node", `a-${node.kind}`, extra, art.node === node.id ? "selected" : ""].filter(Boolean).join(" ");
    return s("g", {
      class: classes, transform: `translate(${fixed(at.x)} ${fixed(at.y)})`, tabindex: 0, role: "button", "aria-label": `${node.label}, ${kindName}`,
      on: {
        click: () => artSelect(node.id),
        keydown: (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            artSelect(node.id);
          }
        },
      },
    }, s("title", {}, `${node.label} · ${kindName}`), s("circle", {r: radius}), caption ? s("text", {class: "label", y: radius + 14, "text-anchor": "middle"}, caption) : null);
  }

  function around(base, index, count, distance) {
    const angle = (base.angle || 0) + ((index - (count - 1) / 2) * Math.PI) / Math.max(count + 2, 5);
    return {x: base.x + distance * Math.cos(angle), y: base.y + distance * Math.sin(angle), angle};
  }

  const toneOf = (branch) => (branch.state === "merged-clean" ? "ok" : branch.state === "dirty" ? "warn" : branch.state === "protected" ? "violet" : branch.state === "stale" ? "warn" : branch.gone ? "bad" : "info");

  function artOrbit(repo, model) {
    const svg = chartFrame(420, `Orbit: ${repo.name} as the sun, branches as planets (size = commits ahead), worktrees as moons, agents as satellites`);
    const rings = repo.branches.length > 16 ? [200, 310] : [250];
    svg.append(...rings.map((r) => s("circle", {class: "ring", r})));
    const layer = s("g", {});
    repo.branches.forEach((branch, index) => {
      const ring = rings[index % rings.length];
      const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(repo.branches.length, 1);
      const at = {x: ring * Math.cos(angle), y: ring * Math.sin(angle), angle};
      const radius = Math.min(11 + 4 * Math.log2(1 + branch.ahead), 30);
      const node = model.byId.get(`branch:${repo.path}\u0000${branch.name}`);
      branch.worktrees.forEach((wt, slot) => {
        const moon = around(at, slot, branch.worktrees.length, radius + 18);
        const holder = model.byId.get(`wt:${wt.path}`);
        const leaves = model.nodes.filter((entry) => entry.parent === holder.id);
        leaves.forEach((leaf, place) => layer.append(artMark(leaf, around(moon, place, leaves.length, 15), 4.5, leaf.kind === "agent" ? "satellite" : "cargo", null)));
        layer.append(artMark(holder, moon, 7, [wt.state === "changed" ? "dirty" : "", wt.open_work.length ? "open" : ""].filter(Boolean).join(" "), null));
      });
      layer.append(artMark(node, at, radius, `tone-${toneOf(branch)}`, repo.branches.length <= 40 ? short(branch.name).slice(0, 28) : null));
    });
    layer.append(artMark(model.byId.get(`repo:${repo.path}`), {x: 0, y: 0, angle: 0}, 34, "sun", repo.name.split("/").pop()));
    svg.append(layer);
    return svg;
  }

  function artChord(repo) {
    const radius = 300;
    const branches = repo.branches;
    const spots = new Map(branches.map((branch, index) => {
      const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(branches.length, 1);
      return [branch.name, {x: radius * Math.cos(angle), y: radius * Math.sin(angle), angle}];
    }));
    const svg = chartFrame(440, `Chord: branch overlap in ${repo.name}; band = files changed by both, dashed = merge`);
    const arcs = s("g", {});
    for (const overlap of repo.overlaps) {
      const from = spots.get(overlap.a);
      const to = spots.get(overlap.b);
      if (from && to) {
        arcs.append(s("path", {class: "edge t-alarm", d: `M${fixed(from.x)},${fixed(from.y)} Q0,0 ${fixed(to.x)},${fixed(to.y)}`, "stroke-width": fixed(width(overlap.count))},
          s("title", {}, `${overlap.a} ↔ ${overlap.b}: ${overlap.count} shared files (conflict risk)\n${overlap.files.join("\n")}`)));
      }
    }
    for (const merge of repo.merges) {
      const from = spots.get(merge.from);
      const to = spots.get(merge.into);
      if (from && to && from !== to) {
        const control = {x: (from.x + to.x) * 0.3, y: (from.y + to.y) * 0.3};
        arcs.append(s("path", {class: "edge t-grant merge", d: `M${fixed(from.x)},${fixed(from.y)} Q${fixed(control.x)},${fixed(control.y)} ${fixed(to.x)},${fixed(to.y)}`, "stroke-width": 2, "marker-end": "url(#tip-grant)"},
          s("title", {}, `${merge.from} → ${merge.into}: merged by ${merge.by}`)));
      }
    }
    for (const edge of flowEdges(repo)) {
      const from = spots.get(edge.from);
      const to = spots.get(edge.into);
      const bend = edge.side === "pull" ? 0.55 : 0.15;
      arcs.append(s("path", {class: "edge t-direct flow", "data-side": edge.side, d: `M${fixed(from.x)},${fixed(from.y)} Q${fixed((from.x + to.x) * bend)},${fixed((from.y + to.y) * bend)} ${fixed(to.x)},${fixed(to.y)}`, "stroke-width": 2, "marker-end": "url(#tip-direct)"},
        s("title", {}, `${edge.from} → ${edge.into}: merge flow, ${edge.side === "pull" ? `${edge.into} pulls ${edge.ref} before the gate` : `${edge.from} merges into ${edge.ref} when done`}`)));
    }
    const marks = branches.map((branch) => artMark({id: `branch:${repo.path}\u0000${branch.name}`, kind: "branch", label: branch.name}, spots.get(branch.name), 8, `tone-${toneOf(branch)}`, null));
    const labels = branches.map((branch) => {
      const at = spots.get(branch.name);
      const cos = Math.cos(at.angle);
      return s("text", {class: "label", x: fixed(at.x * 1.07), y: fixed(at.y * 1.07), dy: "0.35em", "text-anchor": cos > 0.3 ? "start" : cos < -0.3 ? "end" : "middle"}, short(branch.name).slice(0, 26));
    });
    svg.append(arcs, s("g", {}, marks), s("g", {}, labels));
    return svg;
  }

  function artSwimlane(repo) {
    const lanes = repo.branches;
    const begin = state.since;
    const end = Math.max(state.until, state.since + 1);
    const [left, right, top, lane, full] = [200, 24, 40, 34, 1120];
    const height = top + lanes.length * lane + 12;
    const x = (ts) => left + ((Math.min(Math.max(ts, begin), end) - begin) / (end - begin)) * (full - left - right);
    const svg = s("svg", {viewBox: `0 0 ${full} ${height}`, class: "chart", role: "img", "aria-label": `Swimlane: commits, reviews, gates and pushes per branch of ${repo.name}`}, defs());
    lanes.forEach((branch, index) => {
      svg.append(s("rect", {class: index % 2 ? "lane odd" : "lane", x: 0, y: top + index * lane, width: full, height: lane}));
      svg.append(s("text", {class: "lane-label", x: 14, y: top + index * lane + lane / 2, dy: "0.35em", on: {click: () => artSelect(`branch:${repo.path}\u0000${branch.name}`)}}, short(branch.name).slice(0, 26)));
    });
    for (let index = 0; index <= 6; index += 1) {
      const ts = begin + ((end - begin) * index) / 6;
      svg.append(s("line", {class: "grid", x1: fixed(x(ts)), x2: fixed(x(ts)), y1: top - 6, y2: height - 8}));
      svg.append(s("text", {class: "axis", x: fixed(x(ts)), y: top - 14, "text-anchor": index === 0 ? "start" : index === 6 ? "end" : "middle"}, (end - begin > DAY ? absolute : clock).format(stampOf(ts))));
    }
    const marks = s("g", {});
    lanes.forEach((branch, index) => {
      const y = top + index * lane + lane / 2;
      const shapes = {commit: `M-4,0 a4,4 0 1,0 8,0 a4,4 0 1,0 -8,0`, review: "M-4,-4 h8 v8 h-8 z", gate: "M0,-5 L5,4 L-5,4 z", push: "M0,-6 L5,0 L2,0 L2,5 L-2,5 L-2,0 L-5,0 z"};
      for (const event of branch.events.filter((entry) => entry.ts >= begin && entry.ts <= end)) {
        const tone = event.ok === false ? "bad" : event.kind === "push" ? "info" : event.kind === "commit" ? "ok" : event.ok ? "ok" : "neutral";
        marks.append(s("g", {class: `lane-mark tone-${tone}`, transform: `translate(${fixed(x(event.ts))} ${y})`},
          s("title", {}, `${clock.format(stampOf(event.ts))} · ${LANE_MARKS[event.kind][0]}: ${event.title}`), s("path", {d: shapes[event.kind]})));
      }
    });
    svg.append(marks);
    return svg;
  }

  function artLegend(view) {
    const words = {
      orbit: "Sun = repository · planet = branch, size = commits ahead · moon = worktree · satellite = agent or artifact",
      chord: "Band = files both branches change (from the reviews in the hub, known only there) · dashed = merge per gc classification · dotted = merge flow of the worktree",
      swimlane: "Commit = approved review · Gate = review gate and queue runs · Push = runner command with push · Time range = 24 h ▾",
    };
    const marks = view === "swimlane" ? Object.values(LANE_MARKS).map(([label, name]) => h("span", {}, icon(name), label)) : [];
    return h("div", {class: "legend"}, marks, h("span", {class: "muted"}, words[view]));
  }

  function artPanel(model) {
    const node = model.byId.get(art.node);
    if (!node) {
      return [h("h2", {class: "panel-title"}, "Details"), h("p", {class: "muted"}, "Click a repository, a branch, a worktree, an agent or an artifact.")];
    }
    const [kindName, kindIcon] = ART_KINDS[node.kind];
    const data = node.data;
    const body = [];
    if (node.kind === "repo") {
      body.push(meta([["Path", data.path], ["Remote", data.remote], ["Default", data.default], ["Forge", data.forge], ["As of", data.scanned_at]]),
        h("p", {class: "muted"}, `${data.branches.length} Branches · ${data.branches.reduce((sum, entry) => sum + entry.worktrees.length, 0) + data.detached.length} Worktrees`));
    } else if (node.kind === "branch") {
      body.push(h("div", {class: "states"}, branchStates(data)), meta([["Upstream", data.upstream], ["Head", data.head.slice(0, 12), data.head], ["Merged into", data.merged_into], ["Reason", data.reason]]),
        data.worktrees.map((wt) => flowDetails(wt.flow, data.name)),
        h("h3", {}, "Dry run"), h("pre", {class: "notes"}, data.plan.join("\n")), h("div", {class: "actions"}, deleteButton(data)));
    } else if (node.kind === "worktree") {
      body.push(h("div", {class: "states"}, worktreeStates(data)), workChips(data.open_work), meta([["Path", data.path], ["Branch", data.branch], ["HEAD", data.head.slice(0, 12), data.head]]),
        flowDetails(data.flow, data.branch),
        data.workers.length ? h("div", {class: "who"}, data.workers.map((name) => [face(name, false), person(name)])) : h("p", {class: "muted"}, "No agent works here."),
        data.review ? h("div", {class: "who"}, status(data.review.status), h("span", {}, data.review.title)) : null, h("div", {class: "actions"}, copyButton(data.path)));
    } else if (node.kind === "agent") {
      body.push(h("div", {class: "actions"}, btn("Open agent", "btn small soft", () => openAgent(data.name))));
    } else if (node.kind === "artefact") {
      body.push(meta([["Ref", data.ref], ["Kind", data.kind], ["Task", data.task], ["Since", data.added]]), data.ended ? pill("Task ended: clean up", "warn") : null);
    } else {
      body.push(meta([["Title", data.title], ["Status", data.status]]));
    }
    return [
      h("div", {class: "panel-head"}, h("div", {}, h("h2", {class: "panel-title"}, icon(kindIcon), " ", node.label), h("span", {class: "muted"}, kindName)),
        iconBtn("bi-x-lg", "Close", "btn small ghost", () => artSelect(node.id))),
      ...body,
    ];
  }

  function artifactsScreen() {
    const view = ui.views.artifacts;
    const picker = h("select", {class: "field", "aria-label": "Repository", title: "Repository", on: {change: (event) => {
      art.repo = event.target.value;
      art.node = null;
      drawArtifacts();
    }}});
    const count = h("span", {class: "muted"});
    const reload = iconBtn("bi-arrow-clockwise", "Reload", "btn small soft", fetchTree, "Reload: read the tree state from pkgmgr");
    const stageBox = h("div", {class: "stage"});
    const aside = h("aside", {class: "card panel", "aria-live": "polite"});
    const legendBox = h("div", {});
    const list = h("div", {class: "repos"});
    const search = view === "tree" ? h("input", {type: "search", placeholder: "Filter repo, branch, path or agent …", value: tree.q, "aria-label": "Filter tree", on: {input: (event) => {
      tree.q = event.target.value;
      drawArtifacts();
    }}}) : null;
    const removeAll = view === "tree" ? h("span", {class: "delete-all"}) : null;
    tree.dom = {view, picker, count, stage: stageBox, aside, legend: legendBox, list, removeAll};
    window.setTimeout(() => {
      drawArtifacts();
      fetchTree();
    }, 0);
    const controls = h("div", {class: "card controls"}, viewSwitch("artifacts"), view === "3d" ? layoutTools("artifacts") : view === "tree" ? null : picker,
      h("div", {class: "toolbar", role: "toolbar", "aria-label": "Artifacts"}, search, reload, removeAll), count);
    const body = view === "tree" ? list : h("div", {class: "graph-body"}, h("div", {class: "card stage-card"}, stageBox, legendBox), aside);
    return h("div", {class: "graph"}, controls, body);
  }

  async function fetchTree() {
    if (tree.busy) {
      return;
    }
    tree.busy = true;
    try {
      const response = await fetch("/api/tree", {cache: "no-store"});
      if (response.ok) {
        tree.data = await response.json();
        tree.model = artifactModel(tree.data);
      } else {
        tree.data = {repos: [], scanned: null, error: `/api/tree answered ${response.status}`};
      }
    } catch {
      ui.offline = true;
      tree.data = tree.data || {repos: [], scanned: null, error: "Hub unreachable"};
    }
    tree.busy = false;
    drawArtifacts();
  }

  function drawArtifacts() {
    if (!tree.dom) {
      return;
    }
    if (tree.dom.view === "tree") {
      drawTree();
      return;
    }
    const empty = !tree.data || tree.data.error;
    tree.dom.count.textContent = empty ? "" : `${tree.data.repos.length} repositories · as of ${clock.format(stampOf(tree.data.scanned))}`;
    if (empty) {
      tree.dom.stage.replaceChildren(emptyState(tree.busy || !tree.data ? "Reading repositories …" : "No tree", tree.data ? tree.data.error : "pkgmgr writes the tree every minute while this page is open."));
      tree.dom.aside.replaceChildren();
      return;
    }
    const model = tree.model;
    if (art.node !== null && !model.byId.has(art.node)) {
      art.node = null;
    }
    tree.dom.aside.replaceChildren(...artPanel(model));
    if (tree.dom.view === "3d") {
      stage3d("artifacts", tree.dom.stage);
      return;
    }
    const repo = chosenRepo();
    tree.dom.picker.replaceChildren(...tree.data.repos.map((entry) => h("option", {value: entry.path, selected: entry.path === art.repo}, `${entry.name} (${entry.branches.length})`)));
    tree.dom.legend.replaceChildren(artLegend(tree.dom.view));
    tree.dom.stage.replaceChildren(repo ? {orbit: artOrbit, chord: artChord, swimlane: artSwimlane}[tree.dom.view](repo, model) : emptyState("No repository", "pkgmgr names no repository."));
  }
