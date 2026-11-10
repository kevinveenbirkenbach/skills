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

  async function confirmAct(action) {
    const [, label, question] = actionOf(action);
    if (!window.confirm(question)) {
      return;
    }
    const signed = await signedProof("/api/board/sign", {action}, label);
    if (signed) {
      await act(action, label, {proof: signed.proof});
    }
  }

  function choice(name, options, picked) {
    return h("div", {class: "classes", role: "radiogroup", "aria-label": "Class"}, options.map(([id, label]) => h("label", {class: "check"},
      h("input", {type: "radio", name, value: id, checked: id === picked}), label)));
  }

  const picked = (group) => group.querySelector("input:checked").value;

  function actionButton(action, cls, name) {
    const [, label, , hint] = actionOf(action);
    return h("button", {type: "button", class: cls, ...named(label, hint), on: {click: () => confirmAct(action)}}, name ? icon(name) : null, label);
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
    const clear = iconBtn("bi-life-preserver", label, "btn small danger", () => confirmAct("clear-mayday"), hint);
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
    const night = h("details", {class: "menu"}, h("summary", named("Day/Night"), icon("bi-moon-stars"), caret()), h("div", {class: "menu-box"}, mode,
      h("div", {class: "actions"}, ACTIONS.slice(1).map(([id]) => actionButton(id, "btn small")))));
    const bar = h("div", {class: "toolbar", role: "toolbar", "aria-label": "Controls"}, iconBtn("bi-sort-down", "Priority", "btn small", openAgentOrder, "Priority: agent order in the hierarchy"), night);
    return {bar, mode};
  }

  function drawToolbar() {
    drawSpot();
    const toolbar = graphDom && graphDom.toolbar;
    if (!toolbar) {
      return;
    }
    const [mode, tone] = NIGHT[state.night] || [state.night, "neutral"];
    toolbar.mode.replaceChildren(pill(mode, tone));
  }
