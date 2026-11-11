  async function act(action, label, payload) {
    ui.busy = true;
    const result = await sendJson(`/api/board/${action}`, payload);
    ui.busy = false;
    if (result.data && result.data.runs) {
      toast(`${label}: ${result.data.ok ? "done" : "failed"}`, runLines(result.data), result.data.ok);
    } else {
      toast(`${label}: failed`, [`${result.status} ${result.text}`.trim()], false);
    }
    await load();
    return result.ok && result.data && result.data.ok;
  }

  const actionOf = (action) => ACTIONS.find(([id]) => id === action);

  const nightAgents = () => [...new Map(state.claims.filter((claim) => claim.agent && claim.agent !== HUMAN && claim.session !== "-").map((claim) => [claim.session, claim.agent]))]
    .sort(([one, a], [two, b]) => a.localeCompare(b) || one.localeCompare(two));

  async function confirmAct(action, agents) {
    const [, label, question] = actionOf(action);
    const names = new Map(nightAgents());
    if (!window.confirm(agents.length ? question.replace("all agents", agents.map((sid) => names.get(sid) || sid).join(", ")) : question)) {
      return;
    }
    const chosen = agents.length ? {agents} : {};
    const signed = await signedProof("/api/board/sign", {action, ...chosen}, label);
    if (signed) {
      await act(action, label, {proof: signed.proof, ...chosen});
    }
  }

  function choice(name, options, picked) {
    return h("div", {class: "classes", role: "radiogroup", "aria-label": "Class"}, options.map(([id, label]) => h("label", {class: "check"},
      h("input", {type: "radio", name, value: id, checked: id === picked}), label)));
  }

  const picked = (group) => group.querySelector("input:checked").value;

  function actionButton(action, cls, name, agents) {
    const [, label, , hint] = actionOf(action);
    return h("button", {type: "button", class: cls, ...named(label, hint), on: {click: () => confirmAct(action, agents())}}, name ? icon(name) : null, label);
  }

  function nightChosen() {
    const agents = nightAgents().map(([sid]) => sid);
    const on = agents.filter((sid) => !ui.nightOff.has(sid));
    return on.length === agents.length ? [] : on;
  }

  function syncPicks(toolbar) {
    const boxes = [...toolbar.picks.querySelectorAll("input[data-session]")];
    boxes.forEach((box) => {
      box.checked = !ui.nightOff.has(box.dataset.session);
    });
    toolbar.picks.querySelector("input[data-all]").checked = boxes.every((box) => box.checked);
    const none = boxes.length > 0 && boxes.every((box) => !box.checked);
    toolbar.nightButtons.forEach((button) => {
      button.disabled = none;
    });
  }

  function pickAgents(toolbar, sids, on) {
    sids.forEach((sid) => (on ? ui.nightOff.delete(sid) : ui.nightOff.add(sid)));
    syncPicks(toolbar);
  }

  function drawPicks(toolbar) {
    const agents = nightAgents();
    const box = (label, attrs, sids) => h("label", {class: "check"}, h("input", {type: "checkbox", ...attrs, on: {change: (event) => pickAgents(toolbar, sids, event.target.checked)}}), label);
    toolbar.picks.replaceChildren(box("All", {"data-all": true}, agents.map(([sid]) => sid)), ...agents.map(([sid, name]) => box(name, {"data-session": sid}, [sid])));
    syncPicks(toolbar);
  }

  let spotDom = null;

  function openSpot(open) {
    ui.spot = open;
    spotDom.panel.hidden = !open;
    spotDom.toggle.setAttribute("aria-expanded", String(open));
    window.requestAnimationFrame(refresh3d);
    if (open) {
      spotDom.text.focus();
    }
  }

  function toggleGear() {
    const open = spotDom.gearBox.hidden;
    spotDom.gearBox.replaceChildren(...(open ? [radioSettings(toggleGear)] : []));
    spotDom.gearBox.hidden = !open;
    spotDom.gear.setAttribute("aria-expanded", String(open));
    window.requestAnimationFrame(refresh3d);
  }

  function radioSpot() {
    const {form, recipient, text} = composerForm();
    const gearBox = h("div", {class: "radio-gear", id: "radio-gear", hidden: true});
    const gear = iconBtn("bi-gear", "Radio settings", "btn small ghost spot-toggle", toggleGear, "Radio settings: tones, squelch and read aloud");
    gear.setAttribute("aria-expanded", "false");
    gear.setAttribute("aria-controls", "radio-gear");
    const [, label, , hint] = actionOf("clear-mayday");
    const clear = iconBtn("bi-life-preserver", label, "btn small danger", () => confirmAct("clear-mayday", []), hint);
    const panel = h("section", {class: "card radio-spot", id: "radio-spot", "aria-label": "Radio", hidden: !ui.spot},
      h("div", {class: "spot-head"}, h("h3", {class: "group-title"}, "Radio"), h("span", {class: "spacer"}), gear, clear), h("div", {class: "spot-body"}, form, radioSide(), gearBox));
    const toggle = document.getElementById("radio-open");
    toggle.setAttribute("aria-expanded", String(ui.spot));
    toggle.addEventListener("click", () => openSpot(!ui.spot));
    document.getElementById("spot-host").replaceChildren(panel);
    spotDom = {panel, toggle, gear, gearBox, text, clear, recipient, names: ""};
  }

  function openRadio() {
    openSpot(true);
  }

  function drawSpot() {
    spotDom.clear.disabled = !state.silence;
    const names = agentNames();
    if (JSON.stringify(names) !== spotDom.names) {
      spotDom.names = JSON.stringify(names);
      const chosen = spotDom.recipient.value;
      spotDom.recipient.replaceChildren(...names.map((name) => h("option", {value: name, selected: name === chosen}, name)));
    }
  }

  function agentsToolbar() {
    const mode = h("span", {});
    const picks = h("div", {class: "night-picks", role: "group", "aria-label": "Agents"});
    const nightButtons = ACTIONS.slice(1).map(([id]) => actionButton(id, "btn small", null, nightChosen));
    const night = h("details", {class: "menu"}, h("summary", named("Day/Night"), icon("bi-moon-stars"), caret()), h("div", {class: "menu-box"}, mode, picks,
      h("div", {class: "actions"}, nightButtons)));
    const bar = h("div", {class: "toolbar", role: "toolbar", "aria-label": "Controls"}, iconBtn("bi-sort-down", "Priority", "btn small", openAgentOrder, "Priority: agent order in the hierarchy"), night, statusMenu());
    return {bar, mode, picks, nightButtons, agents: ""};
  }

  function lookBox(id, label, on, run) {
    const state = Object.hasOwn(PRESENCE, id) ? {class: "check presence", "data-state": id, "data-tone": PRESENCE[id][2]} : {class: "check"};
    return h("label", state, h("input", {type: "checkbox", checked: on, "data-look": id, on: {change: (event) => run(event.target.checked)}}), state["data-state"] ? icon(PRESENCE[id][1], "glyph") : null, label);
  }

  function setLook(change) {
    change();
    keep(STORE.status, {hidden: [...look.hidden], faces: look.faces});
    render(false);
    drawAgent();
  }

  function statusMenu() {
    return h("details", {class: "menu"}, h("summary", named("Status", "Status: which agent states show their symbol, and faces in 3D"), icon("bi-activity"), caret()),
      h("div", {class: "menu-box"}, h("h3", {}, "Agent states"),
        Object.entries(PRESENCE).map(([id, [label]]) => lookBox(id, label, !look.hidden.has(id), (on) => setLook(() => (on ? look.hidden.delete(id) : look.hidden.add(id))))),
        h("h3", {}, "3D"),
        lookBox("faces", "Faces in 3D", look.faces, (on) => setLook(() => {
          look.faces = on;
        }))));
  }

  function drawToolbar() {
    drawSpot();
    const toolbar = graphDom && graphDom.toolbar;
    if (!toolbar) {
      return;
    }
    const [mode, tone] = NIGHT[state.night] || [state.night, "neutral"];
    const alone = Object.values(state.night_parts).filter((part) => part !== "day").length;
    toolbar.mode.replaceChildren(pill(mode, tone), alone ? pill(`${alone} alone`, "warn") : null);
    const agents = JSON.stringify(nightAgents());
    if (agents !== toolbar.agents) {
      toolbar.agents = agents;
      drawPicks(toolbar);
    }
  }
