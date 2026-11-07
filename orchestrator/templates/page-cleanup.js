  const CLEANUP_POLL = 2000;
  const CLEANUP_PATIENCE = 900000;
  const RESULT_LABELS = {done: ["gelöscht", "ok"], refused: ["verweigert", "bad"], failed: ["fehlgeschlagen", "bad"]};

  function planOf(item) {
    const repo = (tree.data.repos || []).find((entry) => entry.path === item.repository);
    const entry = repo ? repo.branches.find((candidate) => candidate.name === item.branch) : null;
    return {repo, entry};
  }

  function deleteDialog(items) {
    if (!items.length) {
      return;
    }
    const rows = items.map((item) => {
      const {repo, entry} = planOf(item);
      return h("li", {class: "dry-run"},
        h("div", {class: "row"}, h("strong", {}, repo ? repo.name : item.repository), h("code", {}, item.branch)),
        h("pre", {}, (entry ? entry.plan : [`${item.branch} @ ${item.tip.slice(0, 12)}`]).join("\n")));
    });
    const outcome = h("div", {class: "mini", "aria-live": "polite"});
    const confirm = h("button", {type: "button", class: "btn danger", ...named("Löschen", "Löschen: mit deiner Passkey-Signatur an den Host übergeben")}, icon("bi-trash3"), "Löschen");
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      if (!await removeSigned(items, outcome)) {
        confirm.disabled = false;
      }
    });
    openSheet(items.length > 1 ? `${items.length} gemergte Branches löschen` : `${items[0].branch} löschen`, [
      h("p", {class: "muted"}, "Trockenlauf von pkgmgr branch cleanup --local für genau diese Einträge: Worktree, lokaler Branch, Compose-Stack ohne -v und seine Images. Kein Remote-Branch. Der Host prüft deine Signatur und verweigert jeden Eintrag, dessen Stand sich seither geändert hat."),
      h("ul", {class: "mini", "aria-label": "Trockenlauf"}, rows),
      outcome,
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Abbrechen", "btn ghost", closeSheet), confirm),
    ], false);
  }

  async function removeSigned(items, outcome) {
    const signed = await proofFor(items, "Löschen");
    if (signed === null) {
      outcome.replaceChildren(h("p", {class: "muted"}, "Nicht signiert: nichts wurde übergeben."));
      return false;
    }
    const result = await sendJson("/api/cleanup", {items, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast("Löschen: nicht möglich", fail(result), false);
      outcome.replaceChildren(h("p", {class: "muted"}, `${result.status} ${result.text}`.trim()));
      return false;
    }
    outcome.replaceChildren(h("p", {class: "muted", "data-cleanup": result.data.id}, `Signiert und an den Host übergeben (Job ${result.data.id}); die Path-Unit löscht jetzt.`));
    followCleanup(result.data.id, outcome, Date.now());
    return true;
  }

  async function followCleanup(id, outcome, began) {
    let data = null;
    try {
      const response = await fetch(`/api/cleanup/${encodeURIComponent(id)}`, {cache: "no-store"});
      data = response.ok ? await response.json() : null;
    } catch {
      data = null;
    }
    if (!data || data.status !== "done") {
      if (Date.now() - began < CLEANUP_PATIENCE && outcome.isConnected) {
        window.setTimeout(() => followCleanup(id, outcome, began), CLEANUP_POLL);
      }
      return;
    }
    const lines = data.items.map((item) => `${item.branch}: ${(RESULT_LABELS[item.status] || [item.status])[0]}${item.reason ? ` (${item.reason})` : ""}`);
    outcome.replaceChildren(h("ul", {class: "mini", "aria-label": "Ergebnis"}, data.error ? h("li", {}, data.error) : data.items.map((item) => {
      const [label, tone] = RESULT_LABELS[item.status] || [item.status, "neutral"];
      return h("li", {"data-result": item.status}, h("div", {class: "row"}, h("code", {}, item.branch), pill(label, tone)), item.reason ? h("span", {class: "muted"}, item.reason) : null);
    })));
    const good = !data.error && data.items.every((item) => item.status === "done");
    toast(`Löschen: ${good ? "erledigt" : "nicht alles gelöscht"}`, data.error ? [data.error] : lines, good);
    fetchTree();
  }
