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

  function openSpot(spot, open) {
    ui.spot = open;
    spot.panel.hidden = !open;
    spot.toggle.setAttribute("aria-expanded", String(open));
    window.requestAnimationFrame(refresh3d);
    if (open) {
      spot.text.focus();
    }
  }

  function toggleGear(spot) {
    const open = spot.gearBox.hidden;
    spot.gearBox.replaceChildren(...(open ? [radioSettings(() => toggleGear(spot))] : []));
    spot.gearBox.hidden = !open;
    spot.gear.setAttribute("aria-expanded", String(open));
    window.requestAnimationFrame(refresh3d);
  }

  function radioSpot() {
    const {form, recipient, text} = composerForm();
    const gearBox = h("div", {class: "radio-gear", id: "radio-gear", hidden: true});
    const gear = h("button", {type: "button", class: "btn small ghost icon-only spot-toggle", "aria-expanded": "false", "aria-controls": "radio-gear", ...named("Radio settings", "Radio settings: tones, squelch and read aloud")}, icon("bi-gear"));
    const clear = actionButton("clear-mayday", "btn small danger", "bi-life-preserver", () => []);
    const panel = h("section", {class: "card radio-spot", id: "radio-spot", "aria-label": "Radio", hidden: !ui.spot},
      h("div", {class: "spot-head"}, h("h3", {class: "group-title"}, "Radio"), h("span", {class: "spacer"}), gear, clear), h("div", {class: "spot-body"}, form, gearBox));
    const toggle = h("button", {type: "button", class: "btn small spot-toggle", "aria-expanded": String(ui.spot), "aria-controls": "radio-spot", ...named("Radio", "Radio: post, call or a message to all, with Record and the radio settings")}, icon("bi-broadcast-pin"), caret());
    const spot = {panel, toggle, gear, gearBox, text};
    toggle.addEventListener("click", () => openSpot(spot, !ui.spot));
    gear.addEventListener("click", () => toggleGear(spot));
    return {toggle, panel, clear, recipient};
  }

  function openRadio() {
    ui.spot = true;
    go("agents", null);
    window.setTimeout(() => {
      const field = document.querySelector("#radio-spot textarea");
      if (field) {
        field.focus();
      }
    }, 50);
  }

  function agentsToolbar() {
    const spot = radioSpot();
    const mode = h("span", {});
    const picks = h("div", {class: "night-picks", role: "group", "aria-label": "Agents"});
    const nightButtons = ACTIONS.slice(1).map(([id]) => actionButton(id, "btn small", null, nightChosen));
    const night = h("details", {class: "menu"}, h("summary", named("Day/Night"), icon("bi-moon-stars"), caret()), h("div", {class: "menu-box"}, mode, picks,
      h("div", {class: "actions"}, nightButtons)));
    const bar = h("div", {class: "toolbar", role: "toolbar", "aria-label": "Controls"}, spot.toggle, iconBtn("bi-sort-down", "Priority", "btn small", openAgentOrder, "Priority: agent order in the hierarchy"), night);
    return {bar, spot: spot.panel, clear: spot.clear, recipient: spot.recipient, mode, picks, nightButtons, names: "", agents: ""};
  }

  function drawToolbar() {
    const toolbar = graphDom && graphDom.toolbar;
    if (!toolbar) {
      return;
    }
    const [mode, tone] = NIGHT[state.night] || [state.night, "neutral"];
    const alone = Object.values(state.night_parts).filter((part) => part !== "day").length;
    toolbar.clear.disabled = !state.silence;
    toolbar.mode.replaceChildren(pill(mode, tone), alone ? pill(`${alone} alone`, "warn") : null);
    const agents = JSON.stringify(nightAgents());
    if (agents !== toolbar.agents) {
      toolbar.agents = agents;
      drawPicks(toolbar);
    }
    const names = agentNames();
    if (JSON.stringify(names) !== toolbar.names) {
      toolbar.names = JSON.stringify(names);
      const chosen = toolbar.recipient.value;
      toolbar.recipient.replaceChildren(...names.map((name) => h("option", {value: name, selected: name === chosen}, name)));
    }
  }
