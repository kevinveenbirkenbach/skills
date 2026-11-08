  function fileList(id) {
    if (!files.has(id)) {
      files.set(id, "loading");
      fetch(`/reviews/${encodeURIComponent(id)}/files`, {cache: "no-store"})
        .then((response) => (response.ok ? response.json() : {files: null}))
        .then((data) => files.set(id, Array.isArray(data.files) ? data.files : null))
        .catch(() => files.set(id, null))
        .then(() => {
          if (ui.review === id) {
            drawReviewSheet();
          }
        });
    }
    return files.get(id);
  }

  function reviewOf(id) {
    const pending = state.reviews.find((review) => review.id === id);
    if (pending) {
      return pending;
    }
    const entry = stream.events.find((row) => row.kind === "review" && row.ref.id === id);
    return entry ? {id, title: entry.title, notes: entry.text, created_ts: entry.ts, worktree: entry.ref.worktree, branch: entry.ref.branch, tree: entry.ref.tree, gate: entry.ref.gate, score: entry.ref.score, status: entry.ref.status} : null;
  }

  function reviewSheet(id) {
    ui.review = id;
    ui.file = 0;
    drawReviewSheet();
  }

  function drawReviewSheet() {
    const review = reviewOf(ui.review);
    if (!review) {
      closeSheet();
      toast("Review no longer in the time range", [], false);
      return;
    }
    const item = state.inbox.find((entry) => entry.kind === "review" && entry.id === review.id);
    const list = fileList(review.id);
    const treeNav = h("nav", {class: "card tree", "aria-label": "Changed files"}, treePane(list));
    const diff = h("section", {class: "card diff-pane", "aria-label": "Diff"}, diffPane(list));
    const id = ui.review;
    const head = h("article", {class: "card"},
      h("div", {class: "card-head"}, h("div", {}, h("p", {class: "muted"}, "submitted ", when(review.created_ts))), h("div", {class: "who"}, status(review.status || "pending"), review.gate ? pill(review.gate === "pass" ? "Gate green" : "Gate red", review.gate === "pass" ? "ok" : "bad") : null)),
      meta([["Repo", review.worktree], ["Branch", review.branch], ["Tree", (review.tree || "").slice(0, 12), review.tree], ["Score", review.score]]),
      review.notes ? h("pre", {class: "notes"}, review.notes) : null,
      h("div", {class: "actions"},
        h("a", {class: "btn ghost icon-only", href: `/reviews/${encodeURIComponent(review.id)}/page`, target: "_blank", rel: "noopener noreferrer", ...named("Open full page", "Open full page (new tab)")}, icon("bi-box-arrow-up-right")),
        h("span", {class: "spacer"}),
        item ? actionsFor(item).map((node) => {
          node.addEventListener("click", closeSheet);
          return node;
        }) : null));
    openSheet(review.title, [head, h("div", {class: "split"}, treeNav, diff)], true);
    ui.review = id;
    reviewDom = {tree: treeNav, diff};
  }

  function nest(entries) {
    const root = {dirs: new Map(), files: []};
    for (const [file, index] of entries) {
      const parts = file.path.split("/");
      let node = root;
      for (const part of parts.slice(0, -1)) {
        if (!node.dirs.has(part)) {
          node.dirs.set(part, {dirs: new Map(), files: []});
        }
        node = node.dirs.get(part);
      }
      node.files.push([file, index, parts[parts.length - 1]]);
    }
    return root;
  }

  function stat(file) {
    return h("span", {class: "stat"}, h("span", {class: "add"}, `+${file.added}`), h("span", {class: "del"}, `-${file.removed}`));
  }

  function pick(index, list) {
    ui.file = index;
    for (const entry of reviewDom.tree.querySelectorAll(".file-entry")) {
      if (Number(entry.dataset.index) === index) {
        entry.setAttribute("aria-current", "true");
      } else {
        entry.removeAttribute("aria-current");
      }
    }
    reviewDom.diff.replaceChildren(diffPane(list));
  }

  function branch(node, list) {
    const items = [];
    for (const [name, child] of [...node.dirs].sort(([a], [b]) => a.localeCompare(b))) {
      let label = name;
      let inner = child;
      while (!inner.files.length && inner.dirs.size === 1) {
        const [[next, deeper]] = inner.dirs;
        label = `${label}/${next}`;
        inner = deeper;
      }
      items.push(h("li", {}, h("details", {open: true}, h("summary", {}, h("span", {class: "dir"}, `${label}/`)), branch(inner, list))));
    }
    for (const [file, index, name] of node.files.sort((a, b) => a[2].localeCompare(b[2]))) {
      const [letter, tone] = FILE_STATUS[file.status] || ["?", "neutral"];
      items.push(h("li", {}, h("button", {
        type: "button", class: "file-entry", "data-index": index, "aria-current": index === ui.file ? "true" : null,
        title: file.old ? `${file.old} → ${file.path}` : file.path, on: {click: () => pick(index, list)},
      }, h("span", {class: "letter", "data-tone": tone}, letter), h("span", {class: "name"}, name), stat(file))));
    }
    return h("ul", {class: "tree-list"}, items);
  }

  function treePane(list) {
    if (list === "loading") {
      return h("p", {class: "muted pad"}, "Loading file list …");
    }
    if (!Array.isArray(list) || !list.length) {
      return h("p", {class: "muted pad"}, "No file list. The full page shows all changes.");
    }
    const sections = [...new Set(list.map((file) => file.section))];
    return h("div", {}, sections.map((section) => h("div", {class: "tree-section"},
      sections.length > 1 ? h("h3", {class: "tree-title"}, SECTIONS[section] || section || "Files") : null,
      branch(nest(list.map((file, index) => [file, index]).filter(([file]) => file.section === section)), list))));
  }

  function diffRow(line) {
    if (line.kind === "hunk" || line.kind === "more") {
      return h("tr", {class: line.kind}, h("td", {colspan: 3}), h("td", {class: "code"}, line.text));
    }
    return h("tr", {class: line.kind}, h("td", {class: "num"}, line.old), h("td", {class: "num"}, line.new), h("td", {class: "sign"}, SIGNS[line.kind] || " "), h("td", {class: "code"}, line.text));
  }

  function diffPane(list) {
    if (!Array.isArray(list) || !list.length) {
      return h("p", {class: "muted pad"}, list === "loading" ? "Loading changes …" : "No diff available.");
    }
    const file = list[Math.min(ui.file, list.length - 1)];
    const [letter, tone] = FILE_STATUS[file.status] || ["?", "neutral"];
    return h("div", {},
      h("div", {class: "diff-head"},
        h("span", {class: "letter", "data-tone": tone}, letter),
        h("code", {class: "path"}, file.old ? `${file.old} → ${file.path}` : file.path),
        file.tags.map((tag) => pill(tag, "neutral")),
        h("span", {class: "spacer"}),
        stat(file)),
      file.detail ? h("p", {class: "muted pad"}, file.detail) : null,
      file.lines.length ? h("div", {class: "diff-scroll"}, h("table", {class: "diff"}, h("tbody", {}, file.lines.map(diffRow)))) : null);
  }
