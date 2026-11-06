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

  function boardContent() {
    if (ui.order === null || ui.order.some((name) => !state.priority.includes(name)) || ui.order.length !== state.priority.length) {
      ui.order = [...state.priority];
    }
    const [mode, modeTone] = NIGHT[state.night] || [state.night, "neutral"];
    const broadcast = h("textarea", {"aria-label": "Rundruf", placeholder: "Nachricht an alle Agenten …", on: {input: (event) => {
      ui.draft = event.target.value;
    }}});
    broadcast.value = ui.draft;
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
        boardSheet();
      });
      list.append(item);
    });
    const changed = JSON.stringify(ui.order) !== JSON.stringify(state.priority);
    return h("div", {class: "board"},
      h("article", {class: `card${state.silence ? " alarm" : ""}`},
        h("div", {class: "card-head"}, h("h3", {}, "Mayday"), state.silence ? pill("Funkstille", "bad") : pill("ruhig", "ok")),
        state.silence ? h("p", {class: "text"}, `${state.silence.by}: ${state.silence.text}`) : h("p", {class: "muted"}, "Keine Funkstille aktiv."),
        h("div", {class: "actions"}, h("button", {type: "button", class: "btn danger", disabled: !state.silence, on: {click: () => confirmAct("clear-mayday")}}, "Mayday aufheben"))),
      h("article", {class: "card"},
        h("div", {class: "card-head"}, h("h3", {}, "Rundruf an alle")),
        broadcast,
        h("div", {class: "actions"}, h("span", {class: "spacer"}), h("button", {type: "button", class: "btn soft", on: {click: async () => {
          if (!ui.draft.trim()) {
            return;
          }
          if (await act("broadcast", "Rundruf", {text: ui.draft})) {
            ui.draft = "";
            broadcast.value = "";
          }
        }}}, "Senden"))),
      h("article", {class: "card"},
        h("div", {class: "card-head"}, h("h3", {}, "Tag und Nacht"), pill(mode, modeTone)),
        h("p", {class: "muted"}, "Abend: Agenten beenden ihre Aufgabe. Sonnenuntergang: sie schlafen. Sonnenaufgang: alle wachen auf."),
        h("div", {class: "actions"}, ACTIONS.slice(1).map(([id, label]) => btn(label, "btn", () => confirmAct(id))))),
      h("article", {class: "card"},
        h("div", {class: "card-head"}, h("h3", {}, "Priorität der Agenten"), counter(ui.order.length)),
        ui.order.length ? list : h("p", {class: "muted"}, "Kein Agent mit offener Aufgabe."),
        h("div", {class: "actions"},
          h("span", {class: "muted"}, "Ziehen zum Umsortieren"),
          h("span", {class: "spacer"}),
          h("button", {type: "button", class: "btn ghost", disabled: !changed, on: {click: () => {
            ui.order = [...state.priority];
            boardSheet();
          }}}, "Zurücksetzen"),
          h("button", {type: "button", class: "btn primary", disabled: !changed, on: {click: async () => {
            if (await act("order", "Priorität", {agents: ui.order})) {
              ui.order = null;
              boardSheet();
            }
          }}}, "Reihenfolge speichern"))));
  }

  function boardSheet() {
    openSheet("Steuerung", [boardContent()], true);
  }
