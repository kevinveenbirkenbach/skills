const Ancestry = (() => {
  "use strict";
  const LEVELS = ["none", "quick", "test", "quality-high", "e2e"];
  const ACTIONS = ["commit", "merge", "push", "pr"];
  const LEVEL_ICONS = {none: "bi-circle", quick: "bi-lightning-charge", test: "bi-check2-circle", "quality-high": "bi-shield-check", e2e: "bi-browser-chrome"};
  const SPACING = {column: 170, row: 96, wrap: 8};

  function generations(ids, edges) {
    const parents = new Map(ids.map((id) => [id, []]));
    for (const edge of edges) {
      if (parents.has(edge.child) && parents.has(edge.parent) && edge.child !== edge.parent) {
        parents.get(edge.child).push(edge.parent);
      }
    }
    const depth = new Map();
    const visit = (id, path) => {
      if (depth.has(id)) {
        return depth.get(id);
      }
      if (path.has(id)) {
        return -1;
      }
      path.add(id);
      const above = parents.get(id).map((parent) => visit(parent, path)).filter((value) => value >= 0);
      path.delete(id);
      const value = above.length ? Math.max(...above) + 1 : 0;
      depth.set(id, value);
      return value;
    };
    ids.forEach((id) => visit(id, new Set()));
    return depth;
  }

  function layout(nodes, edges) {
    const ids = nodes.map((node) => node.id);
    const depth = generations(ids, edges);
    const rows = [];
    for (const node of nodes) {
      const generation = depth.get(node.id);
      (rows[generation] = rows[generation] || []).push(node);
    }
    const widest = Math.max(1, ...rows.map((row) => Math.min(row ? row.length : 0, SPACING.wrap)));
    const width = widest * SPACING.column;
    const placed = new Map();
    let line = 0;
    rows.forEach((row, generation) => {
      const anchor = (node) => {
        const xs = edges.filter((edge) => edge.child === node.id && placed.has(edge.parent)).map((edge) => placed.get(edge.parent).x);
        return xs.length ? xs.reduce((sum, x) => sum + x, 0) / xs.length : width / 2;
      };
      const ordered = [...(row || [])].sort((a, b) => anchor(a) - anchor(b) || String(a.label).localeCompare(String(b.label)));
      ordered.forEach((node, index) => {
        const band = Math.floor(index / SPACING.wrap);
        const count = Math.min(SPACING.wrap, ordered.length - band * SPACING.wrap);
        const offset = (width - count * SPACING.column) / 2;
        placed.set(node.id, {...node, generation, x: offset + ((index % SPACING.wrap) + 0.5) * SPACING.column, y: (line + band + 0.5) * SPACING.row});
      });
      line += Math.max(1, Math.ceil(ordered.length / SPACING.wrap));
    });
    const links = edges.filter((edge) => placed.has(edge.child) && placed.has(edge.parent) && edge.child !== edge.parent).map((edge) => {
      const from = placed.get(edge.parent);
      const to = placed.get(edge.child);
      return {...edge, derived: edge.source === "derived", x1: from.x, y1: from.y, x2: to.x, y2: to.y};
    });
    return {nodes: ids.map((id) => placed.get(id)), links, width, height: Math.max(line, 1) * SPACING.row};
  }

  function gateMarks(branch, entry) {
    const resolved = (entry && entry.resolved) || {};
    return ACTIONS.map((action) => {
      const found = resolved[action] || {};
      const level = LEVELS.includes(found.level) ? found.level : "none";
      const source = typeof found.source === "string" ? found.source : "";
      const own = source === branch;
      const from = own ? "own rule" : source ? `from ${source}` : "no rule";
      return {action, level, source, own, inherited: !own, icon: LEVEL_ICONS[level], title: `${action}: ${level} · ${from}`};
    });
  }

  function nextRule(level) {
    return level === null || level === undefined ? LEVELS[0] : LEVELS.indexOf(level) + 1 < LEVELS.length ? LEVELS[LEVELS.indexOf(level) + 1] : null;
  }

  function ruleArgv(repo, branch, action, level) {
    const head = ["--repo", repo, "--branch", branch, "--action", action];
    return level === null ? ["rule", "drop", ...head] : ["rule", "set", ...head, "--level", level];
  }

  function parentArgv(repo, branch, parent, drop) {
    return ["parents", drop ? "drop" : "add", "--repo", repo, "--branch", branch, "--parent", parent];
  }

  return {LEVELS, ACTIONS, LEVEL_ICONS, SPACING, generations, layout, gateMarks, nextRule, ruleArgv, parentArgv};
})();
if (typeof module === "object" && module.exports) {
  module.exports = Ancestry;
}
