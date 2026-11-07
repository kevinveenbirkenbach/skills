  function treeScreen() {
    const search = h("input", {type: "search", placeholder: "Repo, Branch, Pfad oder Agent filtern …", value: tree.q, "aria-label": "Tree filtern", on: {input: (event) => {
      tree.q = event.target.value;
      drawTree();
    }}});
    const count = h("span", {class: "muted"});
    const list = h("div", {class: "repos"});
    tree.dom = {list, count};
    window.setTimeout(() => {
      drawTree();
      fetchTree();
    }, 0);
    return h("div", {}, h("div", {class: "filters"}, search, count, btn("Neu laden", "btn small soft", fetchTree)), list);
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
      }
    } catch {
      ui.offline = true;
    }
    tree.busy = false;
    drawTree();
  }

  function worktreeRow(wt) {
    const review = wt.review;
    return h("div", {class: "wt"},
      h("code", {}, wt.path),
      h("span", {class: "muted", title: wt.head}, wt.head.slice(0, 10)),
      wt.dirty === null ? pill("fehlt", "neutral") : wt.dirty ? pill("geändert", "warn") : pill("sauber", "ok"),
      wt.workers.length ? h("span", {class: "who"}, wt.workers.map((name) => [face(name, false), person(name)])) : h("span", {class: "muted"}, "niemand"),
      review ? [status(review.status), review.gate ? pill(review.gate === "pass" ? "Gate grün" : "Gate rot", review.gate === "pass" ? "ok" : "bad") : null] : null,
      copyButton(wt.path));
  }

  function drawTree() {
    if (!tree.dom) {
      return;
    }
    if (!tree.data || tree.data.error) {
      tree.dom.count.textContent = "";
      tree.dom.list.replaceChildren(emptyState(tree.busy ? "Lese Repositories …" : "Kein Tree", tree.data ? tree.data.error : "pkgmgr schreibt den Tree jede Minute, solange diese Seite offen ist."));
      return;
    }
    const q = tree.q.trim().toLowerCase();
    const hit = (...texts) => !q || texts.some((text) => String(text).toLowerCase().includes(q));
    const repos = [];
    for (const repo of tree.data.repos) {
      const branches = repo.branches.filter((entry) => hit(repo.name, entry.name, ...entry.worktrees.flatMap((wt) => [wt.path, ...wt.workers])));
      const detached = repo.detached.filter((wt) => hit(repo.name, wt.path, ...wt.workers));
      if (branches.length || detached.length) {
        repos.push({repo, branches, detached});
      }
    }
    tree.dom.count.textContent = `${repos.length} Repositories · Stand ${clock.format(stampOf(tree.data.scanned))}`;
    if (!repos.length) {
      tree.dom.list.replaceChildren(emptyState("Nichts gefunden", "Kein Repository passt zum Filter."));
      return;
    }
    tree.dom.list.replaceChildren(...repos.map(({repo, branches, detached}) => {
      const trees = repo.branches.flatMap((entry) => entry.worktrees).concat(repo.detached);
      const dirty = trees.filter((wt) => wt.dirty).length;
      const details = h("details", {class: "card repo", open: Boolean(q) || tree.open.has(repo.path)},
        h("summary", {}, h("span", {}, repo.name), counter(`${repo.branches.length} Branches`), counter(`${trees.length} Worktrees`), dirty ? pill(`${dirty} geändert`, "warn") : null),
        branches.map((entry) => h("div", {class: "branch-row"},
          h("div", {class: "branch-name"}, h("strong", {}, entry.name), entry.upstream ? h("span", {class: "muted"}, `↔ ${entry.upstream}`) : h("span", {class: "muted"}, "ohne Upstream"),
            entry.ahead ? pill(`${entry.ahead} voraus`, "info") : null, entry.behind ? pill(`${entry.behind} zurück`, "warn") : null, entry.gone ? pill("Upstream weg", "bad") : null,
            h("span", {class: "muted", title: entry.head}, entry.head.slice(0, 10))),
          entry.worktrees.map(worktreeRow))),
        detached.length ? h("div", {class: "branch-row"}, h("div", {class: "branch-name"}, h("strong", {}, "losgelöster HEAD")), detached.map(worktreeRow)) : null);
      details.addEventListener("toggle", () => {
        if (details.open) {
          tree.open.add(repo.path);
        } else {
          tree.open.delete(repo.path);
        }
      });
      return details;
    }));
  }
