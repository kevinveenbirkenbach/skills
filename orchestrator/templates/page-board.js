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

  async function confirmAct(action) {
    const [, label, question] = ACTIONS.find(([id]) => id === action);
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

  function toAll() {
    const text = h("textarea", {"aria-label": "Radio to all", placeholder: "Message to all agents …", on: {input: (event) => {
      ui.draft = event.target.value;
    }}});
    text.value = ui.draft;
    const classes = choice("to-all", TO_ALL, "newsletter");
    const send = async () => {
      const cls = picked(classes);
      if (!ui.draft.trim() || (cls === "mayday" && !confirmMayday())) {
        return;
      }
      if (await radioSend({to: "*", text: ui.draft, upload: "", cls, voice: ""})) {
        ui.draft = "";
        text.value = "";
      }
    };
    return h("details", {class: "menu", id: "to-all"}, h("summary", named("Radio to all"), icon("bi-broadcast-pin"), caret()), h("div", {class: "menu-box"},
      text, classes, h("p", {class: "muted"}, "Newsletter arrives as post at the end of the turn; Broadcast, Pan-Pan, Security and Mayday at once. Your passkey signs every message."),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), iconBtn("bi-send", "Send", "btn soft", send, "Send to all"))));
  }

  function openToAll() {
    go("agents", null);
    window.setTimeout(() => {
      const menu = document.getElementById("to-all");
      if (menu) {
        menu.open = true;
        menu.querySelector("textarea").focus();
      }
    }, 50);
  }

  function agentsToolbar() {
    const clear = iconBtn("bi-life-preserver", "Cancel mayday", "btn small danger", () => confirmAct("clear-mayday"));
    const mode = h("span", {});
    const night = h("details", {class: "menu"}, h("summary", named("Day/Night"), icon("bi-moon-stars"), caret()), h("div", {class: "menu-box"}, mode,
      h("p", {class: "muted"}, "Evening: agents finish their task. Sunset: they sleep. Sunrise: all wake up."),
      h("div", {class: "actions"}, ACTIONS.slice(1).map(([id, label]) => btn(label, "btn small", () => confirmAct(id))))));
    return {bar: h("div", {class: "toolbar", role: "toolbar", "aria-label": "Controls"}, toAll(), clear, iconBtn("bi-sort-down", "Priority", "btn small", openAgentOrder, "Priority: agent order in the hierarchy"), night), clear, mode};
  }

  function drawToolbar() {
    if (!graphDom || !graphDom.toolbar) {
      return;
    }
    const [mode, tone] = NIGHT[state.night] || [state.night, "neutral"];
    graphDom.toolbar.clear.disabled = !state.silence;
    graphDom.toolbar.mode.replaceChildren(pill(mode, tone));
  }
