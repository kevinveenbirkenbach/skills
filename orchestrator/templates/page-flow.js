  const WORK_CHIPS = {dirty: ["bi-pencil-square", "nicht committet", "warn"], unpushed: ["bi-cloud-upload", "ungepusht", "info"], unmerged: ["bi-signpost-split", "nicht gemergt", "neutral"], task: ["bi-card-checklist", "Aufgabe offen", "violet"]};
  const FLOW_SIDES = {pull: "zieht vor dem Gate", push: "mergt fertig in"};

  function workChips(reasons) {
    if (!reasons || !reasons.length) {
      return null;
    }
    return h("span", {class: "states work", role: "group", "aria-label": "Offene Arbeit"}, reasons.map((reason) => {
      const [name, label, tone] = Object.hasOwn(WORK_CHIPS, reason) ? WORK_CHIPS[reason] : ["bi-question-circle", reason, "neutral"];
      return h("span", {class: "state", "data-tone": tone, title: `offene Arbeit: ${label}`}, icon(name), label);
    }));
  }

  function flowLine(flow, branch) {
    if (!flow) {
      return null;
    }
    if (flow.source === "invalid") {
      return h("div", {class: "flow invalid", "data-flow": "invalid"}, icon("bi-exclamation-triangle"), "Merge-Flow ungültig: pkgmgr kann die Flow-Datei nicht lesen");
    }
    const refs = (side) => (flow[side].length ? flow[side].map((ref) => h("code", {class: "flow-ref", title: `${FLOW_SIDES[side]}: ${ref}`}, ref)) : h("span", {class: "muted"}, "–"));
    const arrow = () => h("span", {class: "flow-arrow", ...named("fließt nach")}, icon("bi-arrow-right"));
    return h("div", {class: "flow", "data-flow": flow.source, role: "group", "aria-label": `Merge-Flow: ${flow.pull.join(", ") || "keine Quelle"} nach ${branch || "–"} nach ${flow.push.join(", ") || "kein Ziel"}`},
      h("span", {class: "flow-label"}, icon("bi-sign-merge-right"), "Flow"),
      h("span", {class: "flow-side"}, refs("pull")), arrow(),
      h("code", {class: "flow-ref here", title: "dieser Branch"}, branch || "–"), arrow(),
      h("span", {class: "flow-side"}, refs("push")));
  }

  function flowDetails(flow, branch) {
    if (!flow) {
      return h("p", {class: "muted"}, "Kein Merge-Flow gesetzt.");
    }
    if (flow.source === "invalid") {
      return flowLine(flow, branch);
    }
    return [h("h3", {}, "Merge-Flow"), flowLine(flow, branch), meta([["Zieht vor dem Gate", flow.pull.join(", ")], ["Mergt fertig in", flow.push.join(", ")], ["Quelle", flow.source]])];
  }

  function flowTarget(names, ref) {
    if (names.has(ref)) {
      return ref;
    }
    const bare = ref.includes("/") ? ref.slice(ref.indexOf("/") + 1) : "";
    return names.has(bare) ? bare : null;
  }

  function flowEdges(repo) {
    const names = new Set(repo.branches.map((entry) => entry.name));
    const edges = [];
    for (const branch of repo.branches) {
      for (const flow of branch.worktrees.map((wt) => wt.flow).filter((found) => found && found.source !== "invalid")) {
        for (const ref of flow.pull) {
          const from = flowTarget(names, ref);
          if (from && from !== branch.name) {
            edges.push({from, into: branch.name, side: "pull", ref});
          }
        }
        for (const ref of flow.push) {
          const into = flowTarget(names, ref);
          if (into && into !== branch.name) {
            edges.push({from: branch.name, into, side: "push", ref});
          }
        }
      }
    }
    return edges;
  }
