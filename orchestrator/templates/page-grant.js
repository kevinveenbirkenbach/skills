  const GRANT_SELECT = "select";
  const GRANT_MODES = {
    direct: ["Direct", "bi-lightning-charge", "Direct mode", "Direct: every grant button grants at once"],
    [GRANT_SELECT]: ["Select", "bi-check2-square", "Select mode", "Select: every grant button and option adds its item to the selection; Grant grants the selection under one passkey signature, each rule and red-gate review under its own"],
  };
  const PICKED_HINT = "In the selection: take it out with ✕ in the Grant menu";
  const UNPICK_HINT = "Selected: press again to take it out of the selection";
  const SOLO_HINT = "Select: press to add it to the selection; Grant asks its own passkey signature for it";
  const grantView = {tray: null, sig: "", open: false};
  const choices = new Map();

  const grantMode = () => (typeof ViewStore === "object" && ViewStore ? ViewStore.get("approval.mode") : "direct");
  const chosenLabel = (item) => (ui.selected.has(keyOf(item)) ? choices.get(keyOf(item)) : undefined);
  const solo = (item) => !item.held && (item.kind === "rule" || (item.kind === "review" && item.gate !== "pass"));
  const batchable = (item) => selectable(item) || (!item.held && chosenLabel(item) !== undefined);
  const collectable = (item) => batchable(item) || solo(item);
  const collecting = (item) => grantMode() === GRANT_SELECT && collectable(item);
  const picking = (item) => grantMode() === GRANT_SELECT && !item.held;

  /**
   * @param {Object} item a batchable inbox item.
   * @returns {string} the label its grant carries: the picked option, else a decision's recommendation, else "".
   */
  function grantLabel(item) {
    const label = chosenLabel(item);
    if (label !== undefined) {
      return label;
    }
    return item.kind === "decision" ? item.recommended : "";
  }

  function regrant() {
    render(false);
    drawStream();
  }

  function flip(key) {
    choices.delete(key);
    if (ui.selected.has(key)) {
      ui.selected.delete(key);
    } else {
      ui.selected.add(key);
    }
  }

  function collect(item) {
    flip(keyOf(item));
    regrant();
  }

  /**
   * @param {Object} item a decision or a decision row.
   * @param {string} label the picked answer; picking the same answer again takes the item out of the selection.
   */
  function collectPick(item, label) {
    const key = keyOf(item);
    if (chosenLabel(item) === label) {
      collect(item);
      return;
    }
    choices.set(key, label);
    ui.selected.add(key);
    regrant();
  }

  /**
   * @param button - the grant button of item.
   * @param item - a waiting inbox item.
   * @returns button; a picked item's button turns pale green and disabled, and in Select a rule or red-gate review says it gets its own signature.
   */
  function grantPress(button, item) {
    if (!collectable(item)) {
      return button;
    }
    const picked = ui.selected.has(keyOf(item));
    if (picked) {
      button.setAttribute("class", `${button.getAttribute("class")} picked`);
    }
    if (grantMode() !== GRANT_SELECT) {
      button.disabled = picked;
      if (picked) {
        button.setAttribute("title", PICKED_HINT);
      }
      return button;
    }
    button.setAttribute("aria-pressed", String(picked));
    button.setAttribute("title", picked ? UNPICK_HINT : solo(item) ? SOLO_HINT : "Select: press to add it to the selection; Grant grants it");
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
