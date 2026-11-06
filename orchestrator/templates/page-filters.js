  const activeKinds = () => (filter.view ? new Set(state.views[filter.view].kinds) : filter.kinds);
  const activeWaiting = () => (filter.view ? state.views[filter.view].waiting : filter.waiting);

  function filterQuery() {
    const params = new URLSearchParams();
    if (filter.view) {
      params.set("view", filter.view);
    } else {
      params.set("kinds", [...filter.kinds].join(","));
      if (filter.waiting) {
        params.set("waiting", "1");
      }
    }
    for (const name of ["q", "agent", "session", "sub"]) {
      if (filter[name]) {
        params.set(name, filter[name]);
      }
    }
    if (filter.parts.size !== PARTS.length) {
      params.set("parts", [...filter.parts].join(","));
    }
    return params.toString();
  }

  function windowKey() {
    if (ui.preset === -1) {
      return `custom:${ui.from}:${ui.to}`;
    }
    return `${ui.preset}:${ui.asOf === null ? "live" : ui.asOf}`;
  }

  function customize() {
    if (filter.view) {
      filter.kinds = new Set(state.views[filter.view].kinds);
      filter.waiting = state.views[filter.view].waiting;
      filter.view = "";
    }
    filter.saved = "";
  }

  function refilter() {
    drawFilters();
    drawStream();
    fetchEvents();
  }

  function useView(id) {
    filter.view = id;
    filter.saved = "";
    filter.session = "";
    filter.sub = "";
    filter.agent = "";
    filter.q = "";
    if (ui.screen === "stream" && stream.dom) {
      stream.dom.search.value = "";
      refilter();
    } else {
      go("stream", null);
    }
  }

  function useSaved(view) {
    filter.view = "";
    filter.saved = view.name;
    filter.kinds = new Set(view.kinds);
    filter.waiting = view.waiting;
    filter.q = view.q;
    filter.agent = view.agent;
    filter.session = "";
    filter.sub = "";
    if (ui.screen === "stream" && stream.dom) {
      stream.dom.search.value = filter.q;
      refilter();
    } else {
      go("stream", null);
    }
  }

  function saveView() {
    const name = (window.prompt("Name der Ansicht", filter.saved || "") || "").trim();
    if (!name) {
      return;
    }
    const entry = {name: name.slice(0, 60), kinds: [...activeKinds()], waiting: activeWaiting(), q: filter.q, agent: filter.agent};
    userViews = [...userViews.filter((view) => view.name !== entry.name), entry];
    if (!keep(STORE.views, userViews)) {
      toast("Ansicht nur bis zum Neuladen gespeichert", ["Der Browser erlaubt kein localStorage."], false);
    }
    useSaved(entry);
  }

  function dropView(name) {
    userViews = userViews.filter((view) => view.name !== name);
    keep(STORE.views, userViews);
    if (filter.saved === name) {
      filter.saved = "";
    }
    drawFilters();
  }

  function drawFilters() {
    if (!stream.dom) {
      return;
    }
    const kinds = activeKinds();
    stream.dom.categories.replaceChildren(...Object.entries(state.views).map(([id, view]) => h("button", {type: "button", class: "chip preset", "aria-pressed": String(filter.view === id), on: {click: () => useView(id)}}, view.label)));
    const mine = userViews.map((view) => h("span", {class: "chip", "aria-pressed": String(!filter.view && filter.saved === view.name), role: "button", tabindex: 0, on: {
      click: () => useSaved(view),
      keydown: (event) => {
        if (event.key === "Enter") {
          useSaved(view);
        }
      },
    }}, view.name, h("button", {type: "button", class: "x", "aria-label": `${view.name} löschen`, on: {click: (event) => {
      event.stopPropagation();
      dropView(view.name);
    }}}, "×")));
    stream.dom.saved.replaceChildren(...mine, btn("＋ Ansicht speichern", "btn small ghost", saveView));
    const kindChips = KINDS.map(([id, label]) => h("button", {type: "button", class: "chip", "aria-pressed": String(kinds.has(id)), on: {click: () => {
      customize();
      if (filter.kinds.has(id) && filter.kinds.size > 1) {
        filter.kinds.delete(id);
      } else {
        filter.kinds.add(id);
      }
      refilter();
    }}}, label));
    const waiting = h("button", {type: "button", class: "chip", "aria-pressed": String(activeWaiting()), on: {click: () => {
      customize();
      filter.waiting = !filter.waiting;
      refilter();
    }}}, "nur Wartendes");
    stream.dom.kinds.replaceChildren(waiting, ...kindChips);
    const parts = kinds.has("transcript") ? PARTS.map(([id, label]) => h("button", {type: "button", class: "chip", "aria-pressed": String(filter.parts.has(id)), on: {click: () => {
      if (filter.parts.has(id) && filter.parts.size > 1) {
        filter.parts.delete(id);
      } else {
        filter.parts.add(id);
      }
      refilter();
    }}}, label)) : [h("span", {class: "muted"}, "Erst mit der Art Transkripte.")];
    stream.dom.parts.replaceChildren(...parts);
    const focus = filter.sub || filter.session || filter.agent ? h("span", {class: "chip", "aria-pressed": "true"}, filter.sub ? `Subagent ${filter.sub.slice(0, 12)}` : filter.session ? `Session ${filter.session.slice(0, 8)}` : `Agent ${filter.agent}`,
      h("button", {type: "button", class: "x", "aria-label": "Filter entfernen", on: {click: () => {
        filter.sub = "";
        filter.session = "";
        filter.agent = "";
        refilter();
      }}}, "×")) : null;
    stream.dom.focus.replaceChildren(...(focus ? [focus] : []));
  }
