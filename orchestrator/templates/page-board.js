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

  function confirmAct(action) {
    const [, label, question] = ACTIONS.find(([id]) => id === action);
    if (window.confirm(question)) {
      act(action, label, {});
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
      const label = TO_ALL.find(([id]) => id === cls)[1];
      if (!ui.draft.trim() || (cls === "mayday" && !window.confirm("Mayday an alle senden? Alle Agenten pausieren schreibende Schritte, bis du ihn aufhebst."))) {
        return;
      }
      if (await act("broadcast", `Funk an alle (${label})`, {text: ui.draft, class: cls})) {
        ui.draft = "";
        text.value = "";
      }
    };
    return h("details", {class: "menu", id: "to-all"}, h("summary", {}, "Funk an alle ▾"), h("div", {class: "menu-box"},
      text, classes, h("p", {class: "muted"}, "Newsletter kommt als Post am Ende des Zuges; Broadcast, Pan-Pan, Security und Mayday sofort."),
      h("div", {class: "actions"}, h("span", {class: "spacer"}), btn("Senden", "btn soft", send))));
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
    const clear = btn("Mayday aufheben", "btn small danger", () => confirmAct("clear-mayday"));
    const mode = h("span", {});
    const night = h("details", {class: "menu"}, h("summary", {}, "Tag/Nacht ▾"), h("div", {class: "menu-box"}, mode,
      h("p", {class: "muted"}, "Abend: Agenten beenden ihre Aufgabe. Sonnenuntergang: sie schlafen. Sonnenaufgang: alle wachen auf."),
      h("div", {class: "actions"}, ACTIONS.slice(1).map(([id, label]) => btn(label, "btn small", () => confirmAct(id))))));
    return {bar: h("div", {class: "toolbar", role: "toolbar", "aria-label": "Steuerung"}, toAll(), clear, btn("Priorität", "btn small", prioritySheet), night), clear, mode};
  }

  function drawToolbar() {
    if (!graphDom || !graphDom.toolbar) {
      return;
    }
    const [mode, tone] = NIGHT[state.night] || [state.night, "neutral"];
    graphDom.toolbar.clear.disabled = !state.silence;
    graphDom.toolbar.mode.replaceChildren(pill(mode, tone));
  }

  function priorityContent() {
    if (ui.order === null || ui.order.some((name) => !state.priority.includes(name)) || ui.order.length !== state.priority.length) {
      ui.order = [...state.priority];
    }
    const list = h("ol", {class: "order-list"});
    let dragged = null;
    ui.order.forEach((name, index) => {
      const item = h("li", {draggable: "true", "data-name": name}, h("span", {class: "rank"}, `${index + 1}.`), face(name, false), person(name));
      item.addEventListener("dragstart", (event) => {
        dragged = name;
        item.classList.add("dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", name);
      });
      item.addEventListener("dragend", () => item.classList.remove("dragging"));
      item.addEventListener("dragover", (event) => event.preventDefault());
      item.addEventListener("drop", (event) => {
        event.preventDefault();
        if (dragged === null || dragged === name) {
          return;
        }
        const next = ui.order.filter((entry) => entry !== dragged);
        next.splice(next.indexOf(name) + (ui.order.indexOf(dragged) < ui.order.indexOf(name) ? 1 : 0), 0, dragged);
        ui.order = next;
        prioritySheet();
      });
      list.append(item);
    });
    const changed = JSON.stringify(ui.order) !== JSON.stringify(state.priority);
    return [
      ui.order.length ? list : h("p", {class: "muted"}, "Kein Agent mit offener Aufgabe."),
      h("div", {class: "actions"},
        h("span", {class: "muted"}, "Ziehen zum Umsortieren"),
        h("span", {class: "spacer"}),
        h("button", {type: "button", class: "btn ghost", disabled: !changed, on: {click: () => {
          ui.order = [...state.priority];
          prioritySheet();
        }}}, "Zurücksetzen"),
        h("button", {type: "button", class: "btn primary", disabled: !changed, on: {click: async () => {
          if (await act("order", "Priorität", {agents: ui.order})) {
            ui.order = null;
            prioritySheet();
          }
        }}}, "Reihenfolge speichern")),
    ];
  }

  function prioritySheet() {
    openSheet("Priorität der Agenten", priorityContent(), false);
  }
