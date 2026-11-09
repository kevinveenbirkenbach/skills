  const chip = (name, label, tone, count) => h("span", {class: "state", "data-tone": tone, role: "img", ...named(label)}, icon(name), count === undefined ? null : String(count));

  function branchStates(entry) {
    return [
      entry.state === "merged-clean" || entry.merged_by ? chip("bi-sign-merge-left", `merged${entry.merged_by ? ` by ${entry.merged_by}` : ""}${entry.merged_into ? ` into ${entry.merged_into}` : ""}`, "ok") : null,
      entry.state === "unmerged" ? chip("bi-signpost-split", "not merged", "neutral") : null,
      entry.state === "protected" ? chip("bi-shield-lock", "protected", "violet") : null,
      entry.state === "stale" ? chip("bi-hourglass-bottom", "stale", "warn") : null,
      entry.ahead && entry.upstream ? chip("bi-cloud-upload", `${entry.ahead} commits unpushed`, "info", entry.ahead) : null,
      entry.behind ? chip("bi-arrow-down-circle", `${entry.behind} commits behind`, "warn", entry.behind) : null,
      entry.gone ? chip("bi-cloud-slash", "upstream gone", "bad") : null,
      !entry.upstream && !entry.gone ? chip("bi-cloud-slash", "no upstream", "neutral") : null,
      entry.skip ? chip("bi-slash-circle", `gc skips: ${entry.skip}`, "bad") : null,
    ];
  }

  function worktreeStates(wt) {
    const counts = [wt.staged, wt.unstaged, wt.untracked];
    const changed = counts.every((value) => typeof value === "number") ? counts.reduce((sum, value) => sum + value, 0) : undefined;
    return [
      wt.state === "clean" ? chip("bi-check-circle", "clean", "ok") : null,
      wt.state === "changed" ? chip("bi-pencil-square", changed === undefined ? "uncommitted changes" : `not committed: ${wt.staged} staged, ${wt.unstaged} changed, ${wt.untracked} new`, "warn", changed) : null,
      wt.state === "missing" ? chip("bi-question-circle", "worktree missing", "neutral") : null,
      wt.locked ? chip("bi-lock-fill", `locked: ${wt.locked}`, "warn") : null,
    ];
  }

  function deleteButton(entry) {
    if (!entry.cleanup) {
      return null;
    }
    const ready = tree.data.delete_ready === true;
    const hint = ready ? `Delete: remove ${entry.name} locally, after dry run and signature` : `Delete blocked: ${tree.data.delete_reason || "delete_ready is false"}`;
    const button = iconBtn("bi-trash3", "Delete", "btn small danger", () => deleteDialog([entry.cleanup]), hint);
    button.disabled = !ready;
    return h("span", {class: "hint", title: hint}, button);
  }

  function deleteAll() {
    const items = (tree.data.repos || []).flatMap((repo) => repo.branches).filter((entry) => entry.cleanup).map((entry) => entry.cleanup);
    const ready = tree.data.delete_ready === true && items.length > 0;
    const hint = tree.data.delete_ready !== true ? `Delete all merged blocked: ${tree.data.delete_reason || "delete_ready is false"}` : items.length ? `Delete all merged: ${items.length} branches after dry run and signature` : "Delete all merged: no merged branch without a skip reason";
    const button = iconBtn("bi-trash3-fill", "Delete all merged", "btn small danger", () => deleteDialog(items), hint);
    button.disabled = !ready;
    return h("span", {class: "hint", title: hint}, button, items.length ? counter(items.length) : null);
  }

  function leafRow(found) {
    return h("li", {class: "leaf"}, h("span", {class: "state", "data-tone": found.ended ? "warn" : "neutral", role: "img", ...named(found.kind)}, icon(ARTEFACT_ICONS[found.kind] || "bi-paperclip")),
      h("code", {}, found.ref), h("span", {class: "muted"}, found.task), found.ended ? pill("task ended", "warn") : null);
  }

  function openWork(wt) {
    return wt.open_work.length ? chip("bi-lightning-charge", `open work: ${wt.open_work.map((reason) => (WORK_CHIPS[reason] || [null, reason])[1]).join(", ")}`, "warn", wt.open_work.length) : null;
  }

  function worktreeRow(wt) {
    const review = wt.review;
    return h("div", {class: wt.open_work.length ? "wt open-work" : "wt", "data-open-work": wt.open_work.join(" ") || null},
      h("div", {class: "wt-head"},
        h("span", {class: "states"}, worktreeStates(wt), openWork(wt)),
        h("code", {}, wt.path),
        h("span", {class: "muted", title: wt.head}, wt.head.slice(0, 10)),
        wt.workers.length ? h("span", {class: "who"}, wt.workers.map((name) => [face(name, false), person(name)])) : h("span", {class: "muted"}, "nobody"),
        review ? [status(review.status), review.gate ? pill(review.gate === "pass" ? "Gate green" : "Gate red", review.gate === "pass" ? "ok" : "bad") : null] : null,
        copyButton(wt.path)),
      flowLine(wt.flow, wt.branch),
      wt.artefacts && wt.artefacts.length ? h("ul", {class: "leaves", "aria-label": "Artifacts"}, wt.artefacts.map(leafRow)) : null);
  }

  function resultOf(repo, entry) {
    const found = (tree.data.cleanups || []).flatMap((result) => result.items.map((item) => ({...item, finished: result.finished}))).filter((item) => item.repository === repo.path && item.branch === entry.name);
    return found.length ? found[found.length - 1] : null;
  }

  function resultChip(result) {
    const [name, label, tone] = result.status === "done" ? ["bi-check2-all", "deleted", "ok"] : result.status === "refused" ? ["bi-x-octagon", "refused", "bad"] : ["bi-exclamation-triangle", "failed", "bad"];
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
      tree.dom.list.replaceChildren(emptyState(tree.busy || !tree.data ? "Reading repositories …" : "No tree", tree.data ? tree.data.error : "pkgmgr writes the tree every minute while this page is open."));
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
    tree.dom.count.textContent = `${repos.length} repositories · as of ${clock.format(stampOf(tree.data.scanned))}${tree.data.delete_ready ? "" : ` · Delete blocked: ${tree.data.delete_reason}`}`;
    if (!repos.length && !tasks.length && !gone.length) {
      tree.dom.list.replaceChildren(emptyState("Nothing found", "No repository matches the filter."));
      return;
    }
    const cards = repos.map(({repo, branches, detached}) => {
      const trees = repo.branches.flatMap((entry) => entry.worktrees).concat(repo.detached);
      const dirty = trees.filter((wt) => wt.dirty).length;
      const merged = repo.branches.filter((entry) => entry.cleanup).length;
      const busy = trees.filter((wt) => wt.open_work.length).length;
      const details = h("details", {class: "card repo", open: Boolean(q) || tree.open.has(repo.path)},
        h("summary", {}, icon("bi-git"), h("span", {}, repo.name), counter(`${repo.branches.length} branches`), counter(`${trees.length} worktrees`),
          dirty ? chip("bi-pencil-square", `${dirty} worktrees with changes`, "warn", dirty) : null, merged ? chip("bi-sign-merge-left", `${merged} merged, deletable`, "ok", merged) : null,
          busy ? chip("bi-lightning-charge", `${busy} worktrees with open work`, "warn", busy) : null),
        branches.map((entry) => branchRow(repo, entry)),
        detached.length ? h("div", {class: "branch-row"}, h("div", {class: "branch-name"}, h("strong", {}, "detached HEAD")), detached.map(worktreeRow)) : null);
      details.addEventListener("toggle", () => {
        if (details.open) {
          tree.open.add(repo.path);
        } else {
          tree.open.delete(repo.path);
        }
      });
      return details;
    });
    const loose = tasks.length ? h("details", {class: "card repo", open: true}, h("summary", {}, icon("bi-card-checklist"), h("span", {}, "Tasks without a worktree"), counter(tasks.length)),
      tasks.map((task) => h("div", {class: "branch-row"}, h("div", {class: "branch-name"}, h("strong", {}, task.task), h("span", {class: "muted"}, task.title), status(task.status)),
        h("ul", {class: "leaves", "aria-label": "Artifacts"}, task.artefacts.map(leafRow))))) : null;
    const past = gone.length ? h("details", {class: "card repo", open: true}, h("summary", {}, icon("bi-trash3"), h("span", {}, "Recently deleted"), counter(gone.length)),
      gone.map((item) => h("div", {class: "branch-row", "data-result": item.status}, h("div", {class: "branch-name"}, h("strong", {}, item.branch), h("code", {}, item.repository), resultChip(item))))) : null;
    tree.dom.list.replaceChildren(...cards, loose || "", past || "");
  }
