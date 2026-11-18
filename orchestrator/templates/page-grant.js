  const GRANT_SELECT = "select";
  const GRANT_MODES = {
    direct: ["Direct", "bi-lightning-charge", "Direct mode", "Direct: every grant button grants at once"],
    [GRANT_SELECT]: ["Select", "bi-check2-square", "Select mode", "Select: every grant button adds its item to the selection; Grant grants the selection under one passkey signature"],
  };
  const PICKED_HINT = "In the selection: take it out with ✕ in the Grant menu";
  const DIRECT_WHY = {rule: "a rule is accepted one at a time", review: "a red gate is never granted in a selection"};
  const grantView = {tray: null, sig: "", open: false};

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
   * @returns button; a picked item's button turns pale green and disabled, and in Select it says why a grant still acts at once.
   */
  function grantPress(button, item) {
    const select = grantMode() === GRANT_SELECT;
    if (!selectable(item)) {
      if (select) {
        button.setAttribute("title", `${button.getAttribute("title")}: acts at once, ${DIRECT_WHY[item.kind]}`);
      }
      return button;
    }
    const picked = ui.selected.has(keyOf(item));
    if (picked) {
      button.disabled = true;
      button.setAttribute("class", `${button.getAttribute("class")} picked`);
      button.setAttribute("title", PICKED_HINT);
    }
    if (select) {
      button.setAttribute("aria-pressed", String(picked));
      if (!picked) {
        button.setAttribute("title", "Select: press to add it to the selection; Grant grants it");
      }
    }
    return button;
  }

  function modeItem(mode) {
    const [, name, text, hint] = GRANT_MODES[mode];
    return h("button", {type: "button", id: `grant-${mode}`, class: "menu-item", "data-mode": mode, ...named(GRANT_MODES[mode][0], hint), on: {click: () => {
      grantView.open = false;
      ViewStore.set("approval.mode", mode);
    }}}, icon(name), text);
  }

  function pickedItem(item) {
    return h("li", {}, h("button", {type: "button", class: "menu-item", ...named(`Remove ${item.title}`, "Remove: take it out of the selection"), on: {click: () => collect(item)}},
      icon("bi-x-lg"), h("span", {class: "grant-picked-title"}, revealed(item.title))));
  }

  /**
   * @returns {Node} the one selection control: Select, or Grant N once something is picked or Select mode is on, with a menu of the rest.
   */
  function grantSplit(mode, actions) {
    const selecting = mode === GRANT_SELECT || actions.chosen.length > 0;
    const [label, name, , hint] = GRANT_MODES[GRANT_SELECT];
    const main = selecting ? actions.grant : h("button", {type: "button", id: "grant-select", class: "btn small", "data-mode": GRANT_SELECT, ...named(label, hint), on: {click: () => ViewStore.set("approval.mode", GRANT_SELECT)}},
      icon(name), h("span", {class: "grant-label"}, label));
    const clear = h("button", {type: "button", class: "menu-item", ...named("Clear", "Clear: empty the selection"), disabled: !actions.chosen.length, on: {click: () => {
      ui.selected.clear();
      regrant();
    }}}, icon("bi-x-lg"), "Clear selection");
    const menu = h("details", {class: "menu grant-menu", open: grantView.open, on: {toggle: (event) => {
      grantView.open = event.currentTarget.open;
    }}}, h("summary", {class: "grant-count", ...named(`${actions.chosen.length} selected`, "More: deny, grant all green, the picked items, clear, mode")}, caret()),
      h("div", {class: "menu-box end grant-menu-box"}, actions.deny, actions.green,
        actions.chosen.length ? h("ul", {class: "grant-picked", "aria-label": "Picked"}, actions.chosen.map(pickedItem)) : null,
        clear, selecting ? modeItem(mode === GRANT_SELECT ? "direct" : GRANT_SELECT) : null));
    return h("div", {class: "grant-split", role: "group", "aria-label": "Selection"}, main, menu);
  }

  function drawGrant() {
    if (!grantView.tray) {
      return;
    }
    const mode = grantMode();
    const actions = selectionActions(state.inbox);
    const sig = JSON.stringify([mode, actions.chosen.map(keyOf), state.inbox.map((item) => [keyOf(item), isGreen(item), item.held]), ui.busy]);
    if (sig === grantView.sig) {
      return;
    }
    grantView.sig = sig;
    grantView.tray.replaceChildren(grantSplit(mode, actions));
  }

  function grantBoot() {
    const bar = document.getElementById("grant-bar");
    grantView.tray = h("div", {class: "grant-tray"});
    bar.replaceChildren(grantView.tray);
    ViewStore.on("approval", regrant);
    drawGrant();
  }
