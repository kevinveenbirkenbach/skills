  const gateStage = {items: [], drag: null};
  const DRAG_SLOP = 6;

  function stageGate(key, change) {
    gateStage.items = gateStage.items.filter((item) => item.key !== key);
    if (change) {
      gateStage.items.push({key, ...change});
    }
    drawArtifacts();
  }

  function stageParent(repo, branch, parent, drop) {
    const key = `parent\u0000${repo}\u0000${branch}\u0000${parent}`;
    const staged = gateStage.items.find((item) => item.key === key);
    stageGate(key, staged && staged.drop === drop ? null : {argv: Ancestry.parentArgv(repo, branch, parent, drop), repo, branch, parent, drop});
  }

  function gatesOf(repo, name) {
    return ((tree.data && tree.data.gates) || {})[repo] ? tree.data.gates[repo][name] || null : null;
  }

  function gateIcons(repo, name) {
    const found = gatesOf(repo, name);
    const own = (found && found.rules) || {};
    return h("span", {class: "gates", role: "group", "aria-label": `Gates of ${name}`}, Ancestry.gateMarks(name, found).map((mark) => {
      const key = `rule\u0000${repo}\u0000${name}\u0000${mark.action}`;
      const staged = gateStage.items.find((item) => item.key === key);
      const current = Object.hasOwn(own, mark.action) ? own[mark.action] : null;
      const level = staged ? staged.level || "none" : mark.level;
      const title = staged ? `${mark.action}: ${staged.level || "inherited"} · staged` : mark.title;
      const cycle = (event) => {
        const group = event.currentTarget.closest(".gates");
        const next = Ancestry.nextRule(staged ? staged.level : current);
        stageGate(key, next === current ? null : {argv: Ancestry.ruleArgv(repo, name, mark.action, next), level: next});
        if (group && group.isConnected) {
          group.replaceWith(gateIcons(repo, name));
        }
      };
      return h("button", {
        type: "button", class: ["gate-mark", "icon-only", mark.inherited && !staged ? "inherited" : "", staged ? "pending" : ""].filter(Boolean).join(" "),
        "data-action": mark.action, "data-level": level, "data-source": mark.source, ...named(`${mark.action} gate`, title), on: {click: cycle},
      }, icon(Ancestry.LEVEL_ICONS[level]));
    }));
  }

  function gateApply() {
    const count = gateStage.items.length;
    if (!count) {
      return null;
    }
    return h("span", {class: "hint gate-apply"},
      iconBtn("bi-check2-all", "Apply", "btn small", applyGates, `Apply ${count} gate changes with one passkey signature`), counter(count),
      iconBtn("bi-x-circle", "Discard", "btn small ghost", () => {
        gateStage.items = [];
        drawArtifacts();
      }, "Discard the staged gate changes"));
  }

  async function applyGates() {
    const items = gateStage.items.map((item) => ({kind: "gate", argv: item.argv}));
    if (!items.length) {
      return;
    }
    const signed = await proofFor(items, "Apply");
    if (signed === null) {
      return;
    }
    const result = await sendJson("/api/gates", {items, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast("Gates: not applied", fail(result), false);
      return;
    }
    gateStage.items = [];
    toast("Gates: signed", [`${items.length} → runner`], true);
    drawArtifacts();
    window.setTimeout(fetchTree, 3000);
  }

  function ancestryChart(plan, label, mark) {
    const width = Math.max(plan.width, Ancestry.SPACING.column);
    const svg = s("svg", {viewBox: `0 0 ${width} ${plan.height}`, width, height: plan.height, class: "chart ancestry", role: "group", "aria-label": label});
    const curve = (link) => `M${fixed(link.x1)},${fixed(link.y1)} C${fixed(link.x1)},${fixed((link.y1 + link.y2) / 2)} ${fixed(link.x2)},${fixed((link.y1 + link.y2) / 2)} ${fixed(link.x2)},${fixed(link.y2)}`;
    svg.append(s("g", {}, plan.links.map((link) => mark.edge(link, curve(link)))), s("g", {}, plan.nodes.map((node) => mark.node(node))));
    return h("div", {class: "ancestry-frame"}, svg);
  }

  function branchAncestry(repo) {
    const names = new Set(repo.branches.map((entry) => entry.name));
    const staged = gateStage.items.filter((item) => item.parent && item.repo === repo.path);
    const edges = [];
    for (const entry of repo.branches) {
      for (const found of (gatesOf(repo.path, entry.name) || {parents: []}).parents) {
        if (names.has(found.parent)) {
          edges.push({child: entry.name, parent: found.parent, source: found.source});
        }
      }
    }
    for (const item of staged.filter((change) => !change.drop && names.has(change.branch) && names.has(change.parent))) {
      if (!edges.some((edge) => edge.child === item.branch && edge.parent === item.parent)) {
        edges.push({child: item.branch, parent: item.parent, source: "staged"});
      }
    }
    const plan = Ancestry.layout(repo.branches.map((entry) => ({id: entry.name, label: entry.name})), edges);
    const dropping = (link) => staged.some((item) => item.drop && item.branch === link.child && item.parent === link.parent);
    return ancestryChart(plan, `Ancestry of ${repo.name}`, {
      edge: (link, d) => s("path", {
        class: ["ancestry-edge", link.derived ? "derived" : "", link.source === "staged" ? "pending" : "", dropping(link) ? "dropping" : ""].filter(Boolean).join(" "),
        d, "data-child": link.child, "data-parent": link.parent, "data-source": link.source,
        on: {click: () => stageParent(repo.path, link.child, link.parent, link.source !== "staged")},
      }, s("title", {}, `${link.parent} → ${link.child} · ${link.source}`)),
      node: (node) => s("g", {
        class: "node a-branch ancestry-node", transform: `translate(${fixed(node.x)} ${fixed(node.y)})`, tabindex: 0, role: "button", "aria-label": node.label,
        "data-repo": repo.path, "data-branch": node.id, "data-generation": node.generation,
        on: {
          pointerdown: (event) => {
            gateStage.drag = event.button === 0 ? {repo: repo.path, branch: node.id, x: event.clientX, y: event.clientY} : null;
          },
          click: () => artSelect(`branch:${repo.path}\u0000${node.id}`),
          keydown: (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              artSelect(`branch:${repo.path}\u0000${node.id}`);
            }
          },
        },
      }, s("title", {}, node.label), s("circle", {r: 9}), s("text", {class: "label", y: 26, "text-anchor": "middle"}, short(node.label).slice(0, 24))),
    });
  }

  function agentAncestry(root) {
    const flat = spawnFlat(root);
    const plan = Ancestry.layout(flat.map(({entry}) => ({id: entry.id, label: entry.label, kind: entry.kind})), flat.filter(({parent}) => parent).map(({entry, parent}) => ({child: entry.id, parent: parent.id, source: "recorded"})));
    const open = (node) => {
      const found = flat.find(({entry}) => entry.id === node.id);
      if (found && found.entry.kind === "twig") {
        focusSub(found.entry.session, found.entry.row.id);
      } else if (found && found.entry.kind !== "operator") {
        select(node.id);
      }
    };
    return ancestryChart(plan, "Ancestry: operator, chair, sessions, subagents", {
      edge: (link, d) => s("path", {class: "ancestry-edge", d, "data-child": link.child, "data-parent": link.parent}),
      node: (node) => s("g", {
        class: `node ancestry-node k-${node.kind}`, transform: `translate(${fixed(node.x)} ${fixed(node.y)})`, tabindex: 0, role: "button", "aria-label": node.label,
        "data-agent": node.id, "data-kind": node.kind, "data-generation": node.generation,
        on: {click: () => open(node), keydown: (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open(node);
          }
        }},
      }, s("title", {}, `${node.label} · ${NODE_KINDS[node.kind] || "Subagent"}`), s("circle", {r: 9}), s("text", {class: "label", y: 26, "text-anchor": "middle"}, short(node.label).slice(0, 24))),
    });
  }

  document.addEventListener("pointerup", (event) => {
    const from = gateStage.drag;
    gateStage.drag = null;
    if (!from || Math.hypot(event.clientX - from.x, event.clientY - from.y) < DRAG_SLOP) {
      return;
    }
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const target = hit && hit.closest("[data-branch]");
    if (target && target.dataset.repo === from.repo && target.dataset.branch !== from.branch) {
      stageParent(from.repo, from.branch, target.dataset.branch, false);
    }
  });
