  async function act(action, label, payload) {
    ui.busy = true;
    const result = await sendJson(`/api/board/${action}`, payload);
    ui.busy = false;
    if (result.data && result.data.runs) {
      toast(`${label}: ${result.data.ok ? "erledigt" : "fehlgeschlagen"}`, runLines(result.data), result.data.ok);
    } else {
      toast(`${label}: fehlgeschlagen`, [`${result.status} ${result.text}`.trim()], false);
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
    return h("div", {class: "classes", role: "radiogroup", "aria-label": "Klasse"}, options.map(([id, label]) => h("label", {class: "check"},
      h("input", {type: "radio", name, value: id, checked: id === picked}), label)));
  }

  const picked = (group) => group.querySelector("input:checked").value;

  function toAll() {
    const text = h("textarea", {"aria-label": "Funk an alle", placeholder: "Nachricht an alle Agenten …", on: {input: (event) => {
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
    return h("details", {class: "menu", id: "to-all"}, h("summary", named("Funk an alle"), icon("bi-broadcast-pin"), caret()), h("div", {class: "menu-box"},
      text, classes, h("p", {class: "muted"}, "Newsletter kommt als Post am Ende des Zuges; Broadcast, Pan-Pan, Security und Mayday sofort. Dein Passkey signiert jede Nachricht."),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), iconBtn("bi-send", "Senden", "btn soft", send, "Senden an alle"))));
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
    const clear = iconBtn("bi-life-preserver", "Mayday aufheben", "btn small danger", () => confirmAct("clear-mayday"));
    const mode = h("span", {});
    const night = h("details", {class: "menu"}, h("summary", named("Tag/Nacht"), icon("bi-moon-stars"), caret()), h("div", {class: "menu-box"}, mode,
      h("p", {class: "muted"}, "Abend: Agenten beenden ihre Aufgabe. Sonnenuntergang: sie schlafen. Sonnenaufgang: alle wachen auf."),
      h("div", {class: "actions"}, ACTIONS.slice(1).map(([id, label]) => btn(label, "btn small", () => confirmAct(id))))));
    return {bar: h("div", {class: "toolbar", role: "toolbar", "aria-label": "Steuerung"}, toAll(), clear, iconBtn("bi-sort-down", "Priorität", "btn small", openAgentOrder, "Priorität: Reihenfolge der Agenten in der Hierarchie"), night), clear, mode};
  }

  function drawToolbar() {
    if (!graphDom || !graphDom.toolbar) {
      return;
    }
    const [mode, tone] = NIGHT[state.night] || [state.night, "neutral"];
    graphDom.toolbar.clear.disabled = !state.silence;
    graphDom.toolbar.mode.replaceChildren(pill(mode, tone));
  }
