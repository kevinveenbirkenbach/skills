  const hier = {chart: null, sig: "", closed: new Set(), ids: 0};
  const OFFICE_ICONS = {chair: "bi-award", line: "bi-person-badge", cluster: "bi-collection", work: "bi-briefcase", other: "bi-signpost-split"};
  const OFFICE_GROUPS = [["cluster", "Organizers", "Organizer"], ["work", "Presidents", "President"], ["other", "Other offices", "Office"]];

  function hierarchyScreen() {
    hier.chart = h("section", {class: "card org-chart", "aria-labelledby": "org-title"});
    orderDom.box = h("section", {class: "card agent-order", id: "agent-order", "aria-labelledby": "agent-order-title"});
    hier.sig = "";
    return h("div", {class: "hierarchy-body"}, hier.chart, orderDom.box);
  }

  function hierarchySig() {
    const held = state.claims.map((claim) => [claim.office, claim.session, claim.agent, claim.work, claim.beat !== null && claim.beat >= state.now - ACTIVE_BEAT]);
    return JSON.stringify([held, state.agent_order, state.people, state.presence, [...look.hidden]]);
  }

  function drawHierarchy(force) {
    if (!hier.chart || !hier.chart.isConnected) {
      hier.chart = null;
      return;
    }
    const sig = hierarchySig();
    if (!force && sig === hier.sig) {
      return;
    }
    hier.sig = sig;
    drawChart();
    drawAgentOrder();
  }

  function focusKey(box) {
    const at = document.activeElement;
    return at && box.contains(at) ? at.dataset.focus || null : null;
  }

  function refocus(box, key) {
    const found = key === null ? null : [...box.querySelectorAll("[data-focus]")].find((element) => element.dataset.focus === key);
    if (found) {
      found.focus();
    }
  }

  function officeBtn(name, label, hint, run, focus) {
    const button = iconBtn(name, label, "btn small ghost", run, hint);
    button.dataset.focus = focus;
    return button;
  }

  function holderOf(claim) {
    return claim.agent || (claim.session === "-" ? "" : claim.session);
  }

  function officeRow(claim, label, title) {
    const who = holderOf(claim);
    const active = claim.beat !== null && claim.beat >= state.now - ACTIVE_BEAT;
    return h("div", {class: "org-row", "data-office": claim.office},
      h("span", {class: "org-office", title: `${title} ${claim.office}`}, icon(OFFICE_ICONS[claim.kind]), h("strong", {}, label)),
      who ? h("button", {type: "button", class: "linkish org-holder", "data-focus": `agent:${claim.office}`, title: `Open ${who}`, on: {click: () => openAgent(who, near(`#main [data-focus="agent:${CSS.escape(claim.office)}"]`))}}, face(who, false), who) : h("span", {class: "muted"}, "–"),
      claim.session === "-" ? null : presenceMark(claim.session, false),
      active ? chip("bi-play-circle", "active", "ok") : chip("bi-pause-circle", "no heartbeat", "neutral"),
      claim.work && claim.work !== "-" ? h("span", {class: "muted org-work", title: claim.work}, short(claim.work)) : null,
      h("span", {class: "org-actions"},
        officeBtn("bi-arrow-left-right", "Hand over", `Hand over: ${claim.office} to another session, with a passkey signature`, () => officeSheet("takeover", claim), `takeover:${claim.office}`),
        officeBtn("bi-person-x", "Recall", `Recall: free ${claim.office}, with a passkey signature`, () => officeSheet("recall", claim), `recall:${claim.office}`)));
  }

  function vacantRow(office, label) {
    return h("div", {class: "org-row vacant", "data-office": office},
      h("span", {class: "org-office"}, icon(OFFICE_ICONS.chair), h("strong", {}, label)),
      pill("vacant", "warn"),
      h("span", {class: "org-actions"}, officeBtn("bi-person-plus", "Appoint", `Appoint: give ${office} to a session, with a passkey signature`, () => officeSheet("appoint", {office, session: "", work: ""}), `appoint:${office}`)));
  }

  function groupRow(glyph, label, count, note) {
    return h("div", {class: "org-row group"}, h("span", {class: "org-office"}, icon(glyph), h("strong", {}, label)), counter(count), h("span", {class: "muted"}, note));
  }

  function orgNode(id, label, row, children) {
    if (!children.length) {
      return h("li", {}, h("div", {class: "org-line"}, h("span", {class: "org-gap", "aria-hidden": "true"}), row));
    }
    const open = !hier.closed.has(id);
    hier.ids += 1;
    const list = h("ul", {class: "org-tree", id: `org-${hier.ids}`, hidden: !open}, children);
    const toggle = h("button", {type: "button", class: "btn small ghost icon-only org-toggle", "aria-expanded": String(open), "aria-controls": list.id, "data-focus": `toggle:${id}`, ...named(`${open ? "Collapse" : "Expand"}: ${label}`)}, icon(open ? "bi-chevron-down" : "bi-chevron-right"));
    toggle.addEventListener("click", () => {
      const now = list.hidden;
      list.hidden = !now;
      toggle.setAttribute("aria-expanded", String(now));
      relabel(toggle, now ? "bi-chevron-down" : "bi-chevron-right", `${now ? "Collapse" : "Expand"}: ${label}`);
      if (now) {
        hier.closed.delete(id);
      } else {
        hier.closed.add(id);
      }
    });
    return h("li", {"data-node": id}, h("div", {class: "org-line"}, toggle, row), list);
  }

  function chartTree() {
    const claims = state.claims;
    const dimensions = new Map();
    for (const claim of claims.filter((entry) => entry.kind === "line")) {
      dimensions.set(claim.dimension, [...(dimensions.get(claim.dimension) || []), claim]);
    }
    const lines = [...dimensions].sort(([a], [b]) => a.localeCompare(b)).map(([dimension, held]) => orgNode(`dimension:${dimension}`, dimension,
      groupRow("bi-diagram-2", dimension, held.length, held.length === 1 ? "line" : "lines"),
      held.map((claim) => orgNode(claim.office, claim.office, officeRow(claim, claim.line, "Representative"), []))));
    const groups = OFFICE_GROUPS.map(([kind, label, title]) => [kind, label, title, claims.filter((entry) => entry.kind === kind)]).filter(([, , , held]) => held.length)
      .map(([kind, label, title, held]) => orgNode(`group:${kind}`, label, groupRow(OFFICE_ICONS[kind], label, held.length, kind === "other" ? "" : `${kind}/…`),
        held.map((claim) => orgNode(claim.office, claim.office, officeRow(claim, kind === "other" ? claim.office : claim.office.slice(kind.length + 1), title), []))));
    const chair = claims.find((entry) => entry.kind === "chair");
    const chairNode = orgNode("chair", "Chair", chair ? officeRow(chair, "Chair", "Office") : vacantRow("chair", "Chair"), [...lines, ...groups]);
    const root = h("div", {class: "org-row org-root"}, h("span", {class: "org-office"}, icon("bi-person-circle"), h("strong", {}, HUMAN)), h("span", {class: "muted"}, "assigns every office with a passkey signature"));
    return h("ul", {class: "org-tree root"}, orgNode("operator", HUMAN, root, [chairNode]));
  }

  function drawChart() {
    const key = focusKey(hier.chart);
    hier.ids = 0;
    const count = state.claims.length;
    hier.chart.replaceChildren(
      h("div", {class: "inbox-head"}, h("h2", {class: "group-title", id: "org-title"}, "Hierarchy", counter(count)),
        h("span", {class: "muted"}, "Formal offices from the council: Operator → Chair → dimensions → lines, plus organizers and presidents"),
        h("span", {class: "spacer"}),
        h("button", {type: "button", class: "btn small soft", "data-focus": "appoint:new", ...named("New office", "New office: give a free office to a session, with a passkey signature"), on: {click: () => officeSheet("appoint", null)}}, icon("bi-person-plus"), "New office")),
      chartTree());
    refocus(hier.chart, key);
  }
