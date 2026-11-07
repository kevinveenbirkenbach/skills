  const chip = (name, label, tone, count) => h("span", {class: "state", "data-tone": tone, role: "img", ...named(label)}, icon(name), count === undefined ? null : String(count));

  function branchStates(entry) {
    return [
      entry.state === "merged-clean" || entry.merged_by ? chip("bi-sign-merge-left", `gemergt${entry.merged_by ? ` durch ${entry.merged_by}` : ""}${entry.merged_into ? ` in ${entry.merged_into}` : ""}`, "ok") : null,
      entry.state === "unmerged" ? chip("bi-signpost-split", "nicht gemergt", "neutral") : null,
      entry.state === "protected" ? chip("bi-shield-lock", "geschützt", "violet") : null,
      entry.state === "stale" ? chip("bi-hourglass-bottom", "veraltet", "warn") : null,
      entry.ahead && entry.upstream ? chip("bi-cloud-upload", `${entry.ahead} Commits ungepusht`, "info", entry.ahead) : null,
      entry.behind ? chip("bi-arrow-down-circle", `${entry.behind} Commits zurück`, "warn", entry.behind) : null,
      entry.gone ? chip("bi-cloud-slash", "Upstream weg", "bad") : null,
      !entry.upstream && !entry.gone ? chip("bi-cloud-slash", "ohne Upstream", "neutral") : null,
      entry.skip ? chip("bi-slash-circle", `gc überspringt: ${entry.skip}`, "bad") : null,
    ];
  }

  function worktreeStates(wt) {
    const counts = [wt.staged, wt.unstaged, wt.untracked];
    const changed = counts.every((value) => typeof value === "number") ? counts.reduce((sum, value) => sum + value, 0) : undefined;
    return [
      wt.state === "clean" ? chip("bi-check-circle", "sauber", "ok") : null,
      wt.state === "changed" ? chip("bi-pencil-square", changed === undefined ? "nicht committete Änderungen" : `nicht committet: ${wt.staged} gestaged, ${wt.unstaged} geändert, ${wt.untracked} neu`, "warn", changed) : null,
      wt.state === "missing" ? chip("bi-question-circle", "Worktree fehlt", "neutral") : null,
      wt.locked ? chip("bi-lock-fill", `gesperrt: ${wt.locked}`, "warn") : null,
    ];
  }

  function deleteButton(entry) {
    if (!entry.cleanup) {
      return null;
    }
    const ready = tree.data.delete_ready === true;
    const hint = ready ? `Löschen: ${entry.name} lokal entfernen, nach Trockenlauf und Signatur` : `Löschen gesperrt: ${tree.data.delete_reason || "delete_ready ist false"}`;
    const button = iconBtn("bi-trash3", "Löschen", "btn small danger", () => deleteDialog([entry.cleanup]), hint);
    button.disabled = !ready;
    return h("span", {class: "hint", title: hint}, button);
  }

  function deleteAll() {
    const items = (tree.data.repos || []).flatMap((repo) => repo.branches).filter((entry) => entry.cleanup).map((entry) => entry.cleanup);
    const ready = tree.data.delete_ready === true && items.length > 0;
    const hint = tree.data.delete_ready !== true ? `Alle gemergten löschen gesperrt: ${tree.data.delete_reason || "delete_ready ist false"}` : items.length ? `Alle gemergten löschen: ${items.length} Branches nach Trockenlauf und Signatur` : "Alle gemergten löschen: kein gemergter Branch ohne Skip-Grund";
    const button = iconBtn("bi-trash3-fill", "Alle gemergten löschen", "btn small danger", () => deleteDialog(items), hint);
    button.disabled = !ready;
    return h("span", {class: "hint", title: hint}, button, items.length ? counter(items.length) : null);
  }

  function leafRow(found) {
    return h("li", {class: "leaf"}, h("span", {class: "state", "data-tone": found.ended ? "warn" : "neutral", role: "img", ...named(found.kind)}, icon(ARTEFACT_ICONS[found.kind] || "bi-paperclip")),
      h("code", {}, found.ref), h("span", {class: "muted"}, found.task), found.ended ? pill("Aufgabe beendet", "warn") : null);
  }

  function openWork(wt) {
    return wt.open_work.length ? chip("bi-lightning-charge", `offene Arbeit: ${wt.open_work.map((reason) => (WORK_CHIPS[reason] || [null, reason])[1]).join(", ")}`, "warn", wt.open_work.length) : null;
  }

  function worktreeRow(wt) {
    const review = wt.review;
    return h("div", {class: wt.open_work.length ? "wt open-work" : "wt", "data-open-work": wt.open_work.join(" ") || null},
      h("div", {class: "wt-head"},
        h("span", {class: "states"}, worktreeStates(wt), openWork(wt)),
        h("code", {}, wt.path),
        h("span", {class: "muted", title: wt.head}, wt.head.slice(0, 10)),
        wt.workers.length ? h("span", {class: "who"}, wt.workers.map((name) => [face(name, false), person(name)])) : h("span", {class: "muted"}, "niemand"),
        review ? [status(review.status), review.gate ? pill(review.gate === "pass" ? "Gate grün" : "Gate rot", review.gate === "pass" ? "ok" : "bad") : null] : null,
        copyButton(wt.path)),
      flowLine(wt.flow, wt.branch),
      wt.artefacts && wt.artefacts.length ? h("ul", {class: "leaves", "aria-label": "Artefakte"}, wt.artefacts.map(leafRow)) : null);
  }

  function resultOf(repo, entry) {
    const found = (tree.data.cleanups || []).flatMap((result) => result.items.map((item) => ({...item, finished: result.finished}))).filter((item) => item.repository === repo.path && item.branch === entry.name);
    return found.length ? found[found.length - 1] : null;
  }

  function resultChip(result) {
    const [name, label, tone] = result.status === "done" ? ["bi-check2-all", "gelöscht", "ok"] : result.status === "refused" ? ["bi-x-octagon", "verweigert", "bad"] : ["bi-exclamation-triangle", "fehlgeschlagen", "bad"];
    return chip(name, `${label}${result.reason ? `: ${result.reason}` : ""}`, tone);
  }

  function branchRow(repo, entry) {
    const result = resultOf(repo, entry);
    return h("div", {class: "branch-row"},
      h("div", {class: "branch-name"}, h("strong", {}, entry.name), h("span", {class: "states"}, branchStates(entry)), entry.upstream ? h("span", {class: "muted"}, `↔ ${entry.upstream}`) : null,
        h("span", {class: "muted", title: entry.head}, entry.head.slice(0, 10)), result ? resultChip(result) : null, h("span", {class: "spacer"}), deleteButton(entry)),
      entry.worktrees.map(worktreeRow));
  }

  function drawTree() {
    if (!tree.dom) {
      return;
    }
    if (!tree.data || tree.data.error) {
      tree.dom.count.textContent = "";
      tree.dom.removeAll.replaceChildren();
      tree.dom.list.replaceChildren(emptyState(tree.busy || !tree.data ? "Lese Repositories …" : "Kein Tree", tree.data ? tree.data.error : "pkgmgr schreibt den Tree jede Minute, solange diese Seite offen ist."));
      return;
    }
    tree.dom.removeAll.replaceChildren(deleteAll());
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
    const tasks = (tree.data.tasks || []).filter((task) => hit(task.task, task.title, ...task.artefacts.map((found) => found.ref)));
    const listed = new Set(tree.data.repos.flatMap((repo) => repo.branches.map((entry) => `${repo.path}\u0000${entry.name}`)));
    const gone = (tree.data.cleanups || []).flatMap((result) => result.items).filter((item) => !listed.has(`${item.repository}\u0000${item.branch}`) && hit(item.repository, item.branch));
    tree.dom.count.textContent = `${repos.length} Repositories · Stand ${clock.format(stampOf(tree.data.scanned))}${tree.data.delete_ready ? "" : ` · Löschen gesperrt: ${tree.data.delete_reason}`}`;
    if (!repos.length && !tasks.length && !gone.length) {
      tree.dom.list.replaceChildren(emptyState("Nichts gefunden", "Kein Repository passt zum Filter."));
      return;
    }
    const cards = repos.map(({repo, branches, detached}) => {
      const trees = repo.branches.flatMap((entry) => entry.worktrees).concat(repo.detached);
      const dirty = trees.filter((wt) => wt.dirty).length;
      const merged = repo.branches.filter((entry) => entry.cleanup).length;
      const busy = trees.filter((wt) => wt.open_work.length).length;
      const details = h("details", {class: "card repo", open: Boolean(q) || tree.open.has(repo.path)},
        h("summary", {}, icon("bi-git"), h("span", {}, repo.name), counter(`${repo.branches.length} Branches`), counter(`${trees.length} Worktrees`),
          dirty ? chip("bi-pencil-square", `${dirty} Worktrees mit Änderungen`, "warn", dirty) : null, merged ? chip("bi-sign-merge-left", `${merged} gemergt, löschbar`, "ok", merged) : null,
          busy ? chip("bi-lightning-charge", `${busy} Worktrees mit offener Arbeit`, "warn", busy) : null),
        branches.map((entry) => branchRow(repo, entry)),
        detached.length ? h("div", {class: "branch-row"}, h("div", {class: "branch-name"}, h("strong", {}, "losgelöster HEAD")), detached.map(worktreeRow)) : null);
      details.addEventListener("toggle", () => {
        if (details.open) {
          tree.open.add(repo.path);
        } else {
          tree.open.delete(repo.path);
        }
      });
      return details;
    });
    const loose = tasks.length ? h("details", {class: "card repo", open: true}, h("summary", {}, icon("bi-card-checklist"), h("span", {}, "Aufgaben ohne Worktree"), counter(tasks.length)),
      tasks.map((task) => h("div", {class: "branch-row"}, h("div", {class: "branch-name"}, h("strong", {}, task.task), h("span", {class: "muted"}, task.title), status(task.status)),
        h("ul", {class: "leaves", "aria-label": "Artefakte"}, task.artefacts.map(leafRow))))) : null;
    const past = gone.length ? h("details", {class: "card repo", open: true}, h("summary", {}, icon("bi-trash3"), h("span", {}, "Zuletzt gelöscht"), counter(gone.length)),
      gone.map((item) => h("div", {class: "branch-row", "data-result": item.status}, h("div", {class: "branch-name"}, h("strong", {}, item.branch), h("code", {}, item.repository), resultChip(item))))) : null;
    tree.dom.list.replaceChildren(...cards, loose || "", past || "");
  }
