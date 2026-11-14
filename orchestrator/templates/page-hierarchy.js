  const hier = {chart: null, sig: "", closed: new Set(), ids: 0};
  const OFFICE_ICONS = {chair: "bi-award", line: "bi-person-badge", cluster: "bi-collection", work: "bi-briefcase", other: "bi-signpost-split"};
  const OFFICE_TITLES = {chair: "Chair", line: "Domain chair", work: "President", cluster: "Organizer", other: "Office"};
  const UNIT_ICONS = {dimension: "bi-diagram-2", work: "bi-briefcase"};

  function hierarchyScreen() {
    hier.chart = h("section", {class: "card org-chart", "data-panel": "agents/hierarchy", "aria-labelledby": "org-title"});
    orderDom.box = h("section", {class: "card agent-order", id: "agent-order", "aria-labelledby": "agent-order-title", "data-panel": "agents/order"});
    orderDom.slot = h("span", {"data-star-slot": ""});
    hier.sig = "";
    return h("div", {class: "hierarchy-body"}, hier.chart, orderDom.box);
  }

  function hierarchySig() {
    const held = state.claims.map((claim) => [claim.office, claim.session, claim.agent, claim.work, claim.beat !== null && claim.beat >= state.now - ACTIVE_BEAT]);
    return JSON.stringify([held, Organigram.dotted(state.claims, state.tasks), state.agent_order, state.people, state.presence, [...look.hidden]]);
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

  function nextOrgId() {
    hier.ids += 1;
    return `org-${hier.ids}`;
  }

  function folder(id, label, list) {
    const open = !hier.closed.has(id);
    list.hidden = !open;
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
      drawLinks(list.closest(".organigram"));
    });
    return toggle;
  }

  function officeHead(claim, toggle) {
    const title = OFFICE_TITLES[claim.kind] || OFFICE_TITLES.other;
    return h("div", {class: "org-head"}, toggle,
      h("span", {class: "org-office", title: `${title} ${claim.office}`}, icon(OFFICE_ICONS[claim.kind] || OFFICE_ICONS.other),
        h("span", {class: "org-name"}, claim.kind === "chair" ? h("strong", {}, title) : [h("span", {class: "org-title"}, title), h("strong", {}, claim.office)])));
  }

  function holderLine(claim) {
    const who = holderOf(claim);
    const active = claim.beat !== null && claim.beat >= state.now - ACTIVE_BEAT;
    return h("div", {class: "org-who"},
      who ? h("button", {type: "button", class: "linkish org-holder", "data-focus": `agent:${claim.office}`, title: `Open ${who}`, on: {click: () => openAgent(who, near(`#main [data-focus="agent:${CSS.escape(claim.office)}"]`))}}, face(who, false), who) : h("span", {class: "muted"}, "–"),
      claim.session === "-" ? null : presenceMark(claim.session, false),
      active ? chip("bi-play-circle", "active", "ok") : chip("bi-pause-circle", "no heartbeat", "neutral"));
  }

  function dottedLines(claim, edges) {
    return edges.filter((edge) => edge.to === claim.office).map((edge) => h("div", {class: "org-dotted", "data-from": edge.from, title: `Additional superior from the register: ${edge.letters} on ${edge.tasks.join(", ")}`},
      icon("bi-bezier2"), `Also under ${edge.from} (${edge.letters})`));
  }

  function officeBox(claim, edges, toggle) {
    return h("div", {class: `org-row org-box${claim.kind === "chair" ? " org-chair" : ""}`, "data-office": claim.office, "data-kind": claim.kind, "data-position": Organigram.position(claim)},
      officeHead(claim, toggle),
      holderLine(claim),
      claim.work && claim.work !== "-" ? h("span", {class: "muted org-work", title: claim.work}, short(claim.work)) : null,
      dottedLines(claim, edges),
      h("span", {class: "org-actions"},
        officeBtn("bi-arrow-left-right", "Hand over", `Hand over: ${claim.office} to another session, with a passkey signature`, () => officeSheet("takeover", claim), `takeover:${claim.office}`),
        officeBtn("bi-person-x", "Recall", `Recall: free ${claim.office}, with a passkey signature`, () => officeSheet("recall", claim), `recall:${claim.office}`)));
  }

  function vacantBox(toggle) {
    return h("div", {class: "org-row org-box org-chair vacant", "data-office": "chair", "data-kind": "chair", "data-position": "chair"},
      h("div", {class: "org-head"}, toggle, h("span", {class: "org-office"}, icon(OFFICE_ICONS.chair), h("strong", {}, "Chair"))),
      pill("vacant", "warn"),
      h("span", {class: "org-actions"}, officeBtn("bi-person-plus", "Appoint", "Appoint: give chair to a session, with a passkey signature", () => officeSheet("appoint", {office: "chair", session: "", work: ""}), "appoint:chair")));
  }

  function unitNode(unit, edges) {
    const list = h("ul", {class: "org-positions", id: nextOrgId()}, unit.positions.map((claim) => h("li", {}, officeBox(claim, edges, null))));
    const note = unit.kind === "work" ? "work/…" : unit.positions.length === 1 ? "line" : "lines";
    return h("li", {class: "org-unit", "data-node": unit.id},
      h("div", {class: "org-row group org-box org-unit-box", "data-unit": unit.id},
        h("div", {class: "org-head"}, folder(unit.id, unit.label, list), h("span", {class: "org-office"}, icon(UNIT_ICONS[unit.kind]), h("strong", {}, unit.label)), counter(unit.positions.length), h("span", {class: "muted"}, note))),
      list);
  }

  function chairPart(chair, staff, units, edges) {
    const below = h("div", {class: "org-below", id: nextOrgId()},
      staff.length ? h("ul", {class: "org-staff", "aria-label": "Staff positions"}, staff.map((claim) => h("li", {}, officeBox(claim, edges, null)))) : null,
      units.length ? h("ul", {class: "org-units", "aria-label": "Line positions"}, units.map((unit) => unitNode(unit, edges))) : null);
    const toggle = staff.length || units.length ? folder("chair", "Chair", below) : null;
    return [h("div", {class: "org-level org-chair-level"}, chair ? officeBox(chair, edges, toggle) : vacantBox(toggle)), below];
  }

  function organigram() {
    const edges = Organigram.dotted(state.claims, state.tasks);
    const {chair, staff, units} = Organigram.chart(state.claims);
    const under = h("div", {class: "org-below", id: nextOrgId()}, chairPart(chair, staff, units, edges));
    const root = h("div", {class: "org-row org-box org-root"},
      h("div", {class: "org-head"}, folder("operator", HUMAN, under), h("span", {class: "org-office"}, icon("bi-person-circle"), h("strong", {}, HUMAN))),
      h("span", {class: "muted"}, "assigns every office with a passkey signature"));
    const links = s("svg", {class: "org-links", "aria-hidden": "true", focusable: "false"});
    const canvas = h("div", {class: "organigram", "data-edges": String(edges.length)}, links, h("div", {class: "org-level"}, root), under);
    canvas.orgEdges = edges;
    const observer = new ResizeObserver(() => (canvas.isConnected ? drawLinks(canvas) : observer.disconnect()));
    observer.observe(canvas);
    return h("div", {class: "org-scroll", role: "region", tabindex: "0", "aria-label": "Organigram"}, canvas);
  }

  function chartBox(base, node) {
    if (!node || !node.getClientRects().length) {
      return null;
    }
    const found = node.getBoundingClientRect();
    return {left: found.left - base.left, top: found.top - base.top, right: found.right - base.left, bottom: found.bottom - base.top};
  }

  function solidBoxes(canvas, boxOf) {
    const units = [...canvas.querySelectorAll(".org-units > .org-unit")].map((unit) => ({box: boxOf(unit.querySelector(".org-unit-box")), positions: [...unit.querySelectorAll(".org-positions > li > .org-box")].map(boxOf).filter(Boolean)}));
    return {root: boxOf(canvas.querySelector(".org-root")), chair: boxOf(canvas.querySelector(".org-chair")), staff: [...canvas.querySelectorAll(".org-staff > li > .org-box")].map(boxOf).filter(Boolean), units: units.filter((unit) => unit.box)};
  }

  function drawLinks(canvas) {
    if (!canvas || !canvas.isConnected) {
      return;
    }
    const base = canvas.getBoundingClientRect();
    const boxOf = (node) => chartBox(base, node);
    const office = (name) => boxOf([...canvas.querySelectorAll(".org-box[data-office]")].find((node) => node.dataset.office === name));
    const dashed = (canvas.orgEdges || []).map((edge) => [edge, office(edge.from), office(edge.to)]).filter(([, from, to]) => from && to);
    const svg = canvas.querySelector(":scope > .org-links");
    svg.setAttribute("width", String(canvas.scrollWidth));
    svg.setAttribute("height", String(canvas.scrollHeight));
    svg.replaceChildren(...Organigram.solid(solidBoxes(canvas, boxOf)).map((d) => s("path", {class: "org-solid", d})),
      ...dashed.map(([edge, from, to]) => s("path", {class: "org-dashed", d: Organigram.dashed(from, to), "data-from": edge.from, "data-to": edge.to}, s("title", {}, `${edge.from} to ${edge.to}: ${edge.letters} on ${edge.tasks.join(", ")}`))));
  }

  function orgLegend() {
    const sample = (kind) => s("svg", {class: `org-sample ${kind}`, viewBox: "0 0 28 8", "aria-hidden": "true", focusable: "false"}, s("line", {x1: "1", y1: "4", x2: "27", y2: "4"}));
    return h("div", {class: "org-legend", role: "note"},
      h("span", {}, sample("solid"), "Line: domain chairs and presidents under the Chair"),
      h("span", {}, h("span", {class: "org-swatch", "aria-hidden": "true"}), "Staff: organizers and single offices beside the Chair"),
      h("span", {}, sample("dashed"), "Additional superior: A or C on a task in the register"));
  }

  function drawChart() {
    const key = focusKey(hier.chart);
    const old = hier.chart.querySelector(".org-scroll");
    const kept = old ? [old.scrollLeft, old.scrollTop] : null;
    const count = state.claims.length;
    const chart = organigram();
    hier.chart.replaceChildren(
      h("div", {class: "inbox-head", "data-star-slot": ""}, h("h2", {class: "group-title", id: "org-title"}, "Organigram", counter(count)),
        h("span", {class: "muted"}, "Formal offices from the council: Operator, Chair, line and staff positions"),
        h("span", {class: "spacer"}),
        h("button", {type: "button", class: "btn small soft", "data-focus": "appoint:new", ...named("New office", "New office: give a free office to a session, with a passkey signature"), on: {click: () => officeSheet("appoint", null)}}, icon("bi-person-plus"), "New office")),
      orgLegend(),
      chart);
    if (kept) {
      [chart.scrollLeft, chart.scrollTop] = kept;
    } else {
      centerChair(chart);
    }
    refocus(hier.chart, key);
  }

  function centerChair(chart) {
    const box = chart.querySelector(".org-chair");
    if (box) {
      const found = box.getBoundingClientRect();
      const frame = chart.getBoundingClientRect();
      chart.scrollLeft += found.left + found.width / 2 - (frame.left + frame.width / 2);
    }
  }
