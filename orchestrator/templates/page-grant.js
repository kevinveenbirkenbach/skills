  const GRANT_SELECT = "select";
  const GRANT_MODES = [
    ["direct", "Direct", "bi-lightning-charge", "Direct: every grant button grants at once"],
    [GRANT_SELECT, "Select", "bi-check2-square", "Select: every grant button adds its item to the selection; the tray grants the selection under one passkey signature"],
  ];
  const DIRECT_WHY = {rule: "a rule is accepted one at a time", review: "a red gate is never granted in a selection"};
  const grantView = {modes: [], tray: null, sig: ""};

  const grantMode = () => (typeof ViewStore === "object" && ViewStore ? ViewStore.get("approval.mode") : "direct");
  const collecting = (item) => grantMode() === GRANT_SELECT && selectable(item);

  function regrant() {
    render(false);
    drawStream();
  }

  function collect(item) {
    const key = keyOf(item);
    if (ui.selected.has(key)) {
      ui.selected.delete(key);
    } else {
      ui.selected.add(key);
    }
    regrant();
  }

  /**
   * @param button - the grant button of item.
   * @param item - a waiting inbox item.
   * @returns button; in Select it shows whether item is in the selection, or why its grant still acts at once.
   */
  function grantPress(button, item) {
    if (grantMode() !== GRANT_SELECT) {
      return button;
    }
    if (!selectable(item)) {
      button.setAttribute("title", `${button.getAttribute("title")}: acts at once, ${DIRECT_WHY[item.kind]}`);
      return button;
    }
    const picked = ui.selected.has(keyOf(item));
    button.setAttribute("aria-pressed", String(picked));
    button.setAttribute("title", picked ? "In the selection: press to take it out" : "Select: press to add it to the selection; the tray grants it");
    return button;
  }

  function drawGrant() {
    if (!grantView.tray) {
      return;
    }
    const mode = grantMode();
    const chosen = state.inbox.filter((item) => ui.selected.has(keyOf(item)));
    const sig = JSON.stringify([mode, chosen.map(keyOf), state.inbox.map((item) => [keyOf(item), isGreen(item), item.held]), ui.busy]);
    if (sig === grantView.sig) {
      return;
    }
    grantView.sig = sig;
    for (const button of grantView.modes) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    }
    grantView.tray.hidden = mode !== GRANT_SELECT;
    grantView.tray.replaceChildren(...(mode === GRANT_SELECT ? [
      h("span", {class: "grant-count", "aria-live": "polite"}, `${chosen.length} selected`),
      ...selectionButtons(state.inbox),
      h("button", {type: "button", class: "btn small ghost", ...named("Clear", "Clear: empty the selection"), disabled: !chosen.length, on: {click: () => {
        ui.selected.clear();
        regrant();
      }}}, icon("bi-x-lg"), "Clear"),
    ] : []));
  }

  function grantBoot() {
    const bar = document.getElementById("grant-bar");
    grantView.modes = GRANT_MODES.map(([mode, label, name, hint]) => h("button", {type: "button", id: `grant-${mode}`, "data-mode": mode, ...named(label, hint), on: {click: () => ViewStore.set("approval.mode", mode)}},
      icon(name), h("span", {class: "grant-label"}, label)));
    grantView.tray = h("div", {class: "grant-tray", role: "group", "aria-label": "Selection"});
    bar.replaceChildren(h("div", {class: "segmented", role: "group", "aria-label": "Grant mode"}, grantView.modes), grantView.tray);
    ViewStore.on("approval", regrant);
    drawGrant();
  }
