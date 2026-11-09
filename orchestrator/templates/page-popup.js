  const pop = {anchor: null, marked: null, closed: null};
  const HITS = 8;
  const popupDialog = () => document.getElementById("popup");
  const popupBox = () => popupDialog().querySelector(".popup-box");
  const near = (selector) => () => document.querySelector(selector);
  // Trip-wire: artifact ids hold NUL, which CSS.escape turns into U+FFFD, so an attribute selector never matches them.
  const pickOf = (id) => () => [...document.querySelectorAll("#main [data-pick]")].find((node) => node.dataset.pick === id) || null;
  const popupHead = (lead, title, ...sub) => h("div", {class: "popup-head"}, lead, h("div", {}, h("h2", {class: "panel-title"}, title), sub), h("span", {class: "spacer"}), iconBtn("bi-x-lg", "Close", "btn small ghost", closePopup));

  function openPopup(label, body, anchor, closed) {
    closePopup();
    pop.anchor = anchor || null;
    pop.closed = closed || null;
    popupDialog().setAttribute("aria-label", label);
    popupBox().replaceChildren(...body);
    popupDialog().show();
    placePopup();
  }

  function closePopup() {
    if (!popupDialog().open) {
      return;
    }
    popupDialog().close();
    markPick(null);
    const closed = pop.closed;
    pop.anchor = null;
    pop.closed = null;
    if (closed) {
      closed();
    }
  }

  function markPick(target) {
    if (pop.marked && pop.marked !== target) {
      pop.marked.classList.remove("picked");
    }
    pop.marked = target;
    if (target) {
      target.classList.add("picked");
    }
  }

  function placePopup() {
    const dialog = popupDialog();
    if (!dialog.open) {
      return;
    }
    const found = pop.anchor ? pop.anchor() : null;
    const target = found instanceof Element && found.isConnected ? found : null;
    markPick(target);
    const shape = target ? target.querySelector("circle") || target : null;
    const box = popupBox();
    box.style.maxHeight = "";
    const at = Popup.place(shape ? shape.getBoundingClientRect() : found instanceof Element ? null : found, {width: box.offsetWidth, height: box.offsetHeight}, {width: dialog.clientWidth, height: dialog.clientHeight});
    box.style.left = `${at.left}px`;
    box.style.top = `${at.top}px`;
    box.style.maxHeight = at.height === null ? "" : `${at.height}px`;
    const line = dialog.querySelector(".leader line");
    line.setAttribute("display", at.line ? "inline" : "none");
    for (const [key, value] of Object.entries(at.line || {})) {
      line.setAttribute(key, value);
    }
  }

  function nodeSearch(nodes, pick) {
    const list = h("div", {class: "chips hits", role: "group", "aria-label": "Search hits"});
    const field = h("input", {type: "search", class: "field", placeholder: "Find a node …", "aria-label": "Find a node", on: {
      input: () => list.replaceChildren(...Popup.hits(nodes(), field.value, HITS).map((node) => h("button", {type: "button", class: "chip", title: node.label, "data-hit": node.id, on: {click: () => pick(node)}}, node.label))),
      keydown: (event) => {
        const [first] = event.key === "Enter" ? Popup.hits(nodes(), field.value, 1) : [];
        if (first) {
          event.preventDefault();
          pick(first);
        }
      },
    }});
    return h("div", {class: "node-search"}, field, list);
  }
