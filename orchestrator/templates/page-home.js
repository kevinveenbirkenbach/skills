  const HOME_PATH = "home.pins";
  const HOME_FETCH = 3000;
  const HOME_MESSAGE = 30000;
  const HOME_MARKS = [['section[aria-label="Recently sent"]', "radio-log"]];
  const homeView = {dom: null, pins: [], tiles: new Map(), hosts: new Map(), messages: new Map(), drag: null, mark: () => null, touched: false, fetched: {}};
  const homeStore = Panels.store(typeof ViewStore === "object" && ViewStore ? ViewStore : Panels.memory(), HOME_PATH);
  const homePins = () => homeView.pins;
  const homeIndex = (key) => homePins().findIndex((pin) => Panels.keyOf(pin) === key);
  const homeWait = (title) => emptyState(title, "The tile fills in on the next poll.");

  function homeFetch(name, work) {
    if (Date.now() - (homeView.fetched[name] || 0) > HOME_FETCH) {
      homeView.fetched[name] = Date.now();
      Promise.resolve(work()).then(() => drawHome());
    }
  }

  function homeStream(size) {
    homeFetch("events", fetchEvents);
    const rows = [...stream.events, ...stream.entries].sort((a, b) => b.ts - a.ts).slice(0, Math.max(3, size.h * 2));
    return rows.length ? h("ol", {class: "feed"}, rows.map(eventRow)) : homeWait(stream.key ? "No entries" : "Loading …");
  }

  async function homeLoadMessage(key, ts, id) {
    const known = homeView.messages.get(key) || {entry: undefined};
    homeView.messages.set(key, {...known, busy: true, at: Date.now()});
    let entry = known.entry;
    try {
      const response = await fetch(`/api/events?from=${Math.floor(ts) - 1}&to=${Math.ceil(ts) + 1}&after=0`, {cache: "no-store"});
      if (response.ok) {
        const data = await response.json();
        entry = [...data.events, ...data.entries].find((row) => String(row.id) === id) || null;
      }
    } catch {
      ui.offline = true;
    }
    homeView.messages.set(key, {entry, busy: false, at: Date.now()});
    drawHome();
  }

  /**
   * @param key - a message pin's raw id, <ts>/<entry id>.
   * @returns the stream entry, null when it no longer exists or the key is malformed, undefined while it loads.
   */
  function homeEntry(key) {
    const cut = key.indexOf("/");
    const ts = Number(key.slice(0, cut));
    const id = key.slice(cut + 1);
    if (cut < 1 || !Number.isFinite(ts)) {
      return null;
    }
    const shown = [...stream.events, ...stream.entries].find((row) => String(row.id) === id);
    const known = homeView.messages.get(key);
    if (!shown && (!known || (!known.busy && Date.now() - known.at > HOME_MESSAGE))) {
      homeLoadMessage(key, ts, id);
    }
    return shown || (known ? known.entry : undefined);
  }

  function homeMessage(key) {
    const entry = homeEntry(key);
    if (entry === undefined) {
      return homeWait("Loading …");
    }
    return entry ? h("ol", {class: "feed"}, eventRow(entry)) : null;
  }

  function homeRadio(id) {
    const host = homeView.hosts.get(id) || radioPart(id);
    homeView.hosts.set(id, host);
    return host;
  }

  function homeTree(draw) {
    if (!tree.data || Date.now() - (homeView.fetched.tree || 0) > HOME_TREE) {
      homeFetch("tree", fetchTree);
    }
    if (!tree.data) {
      return homeWait("Reading repositories …");
    }
    return tree.data.error ? emptyState("No tree", tree.data.error) : draw();
  }

  function homeArt(view) {
    return homeTree(() => {
      const repo = chosenRepo();
      return repo ? {orbit: artOrbit, chord: artChord, swimlane: artSwimlane}[view](repo, tree.model) : emptyState("No repository", "pkgmgr names no repository.");
    });
  }

  const artifactNode = (ref) => (tree.model ? tree.model.byRef.get(ref) || null : null);
  const artifactTitle = (ref) => `Artifact ${(artifactNode(ref) ? artifactNode(ref).id : ref).replace(/\u0000/g, " ")}`;

  function homeArtifact(ref) {
    return homeTree(() => {
      const node = artifactNode(ref);
      return node ? h("div", {class: "home-popup"}, artPopup(node, true)) : null;
    });
  }

  function homeAncestry(path) {
    return homeTree(() => {
      const repo = tree.data.repos.find((entry) => entry.path === path);
      return repo ? branchAncestry(repo) : null;
    });
  }

  function homeOrbit() {
    const kept = [graphDom, positions];
    graphDom = {pulses: null};
    try {
      return orbit();
    } finally {
      [graphDom, positions] = kept;
    }
  }

  function home3d(tab) {
    const id = `${tab}/3d`;
    const pin = homePins().find((entry) => entry.kind === Panels.PANEL && entry.id === id);
    if (pin && !Panels.firstOfGroup(homePins(), pin)) {
      return emptyState("One 3D tile at a time", "Another 3D tile already runs live on Home; unpin it to bring this one to life.");
    }
    const host = homeView.hosts.get(id) || h("div", {class: "stage home-stage"});
    homeView.hosts.set(id, host);
    window.setTimeout(() => host.isConnected && stage3d(tab, host), 0);
    return host;
  }

  function agentTile(key) {
    const node = state.graph.nodes.find((entry) => entry.id === key);
    if (!node && !Object.hasOwn(people(), key)) {
      return null;
    }
    const tasks = node ? node.tasks : [];
    const claims = node ? node.claims : [];
    return h("div", {class: "home-agent"},
      h("div", {class: "who"}, face(key, true), person(nameOf(key)), presenceMark(key, true)),
      h("p", {class: "muted"}, claims.length ? `Offices: ${claims.map((claim) => claim.office).join(", ")}` : "No office"),
      tasks.length ? h("ul", {class: "mini"}, tasks.map((task) => h("li", {}, h("div", {class: "row"}, h("code", {}, task.task), status(task.status)), h("span", {}, dash(task.title)))))
        : h("p", {class: "muted"}, "No open tasks."));
  }

  function homeTask(id) {
    const row = state.tasks.find((entry) => entry.task === id);
    return row ? h("ol", {class: "task-list"}, taskItem(row, etaOf().get(row.task))) : null;
  }

  function homeTaskList() {
    const etas = etaOf();
    return h("ol", {class: "task-list"}, Plan.sortRows(shownTasks(), taskView.sort, taskView.descending).map((row) => taskItem(row, etas.get(row.task))));
  }

  Panels.panel("stream", "Stream", homeStream);
  Panels.panel("radio-log", "Radio log", () => homeRadio("radio-log"), "", [6, 5]);
  Panels.panel("radio", "Radio", () => homeRadio("radio"), "", [12, 7]);
  Panels.panel("radio-device", "Radio: device", () => homeRadio("radio-device"), "", [6, 6]);
  Panels.panel("radio-speak", "Radio: speak", () => homeRadio("radio-speak"), "", [6, 5]);
  Panels.panel("agents/orbit", "Agents: Orbit", homeOrbit);
  Panels.panel("agents/chord", "Agents: Chord", () => chord());
  Panels.panel("agents/swimlane", "Agents: Swimlane", () => swimlane());
  Panels.panel("agents/3d", "Agents: 3D", () => home3d("agents"), "3d");
  Panels.panel("agents/tree", "Agents: spawn tree", () => h("ul", {class: "spawn-tree root"}, spawnItem(spawnTree())));
  Panels.panel("agents/hierarchy", "Agents: organigram", () => organigram());
  Panels.panel("artifacts/orbit", "Artifacts: Orbit", () => homeArt("orbit"));
  Panels.panel("artifacts/chord", "Artifacts: Chord", () => homeArt("chord"));
  Panels.panel("artifacts/swimlane", "Artifacts: Swimlane", () => homeArt("swimlane"));
  Panels.panel("artifacts/3d", "Artifacts: 3D", () => homeTree(() => home3d("artifacts")), "3d");
  Panels.panel("tasks/list", "Tasks: list", homeTaskList);
  Panels.panel("tasks/board", "Tasks: kanban", () => kanbanBoard(shownTasks()));
  Panels.panel("tasks/rasci", "Tasks: RASCI", () => taskMatrix(shownTasks()));
  Panels.panel("tasks/gantt", "Tasks: Gantt", () => ganttChart(shownTasks()));
  Panels.panel("tasks/burn", "Tasks: burndown and burnup", () => burnChart(state.tasks, shownTasks()));
  Panels.panel("tasks/3d", "Tasks: 3D", () => home3d("tasks"), "3d");
  Panels.item("task", (id) => `Task ${id}`, (size, id) => homeTask(id));
  Panels.item("message", "Message", (size, id) => homeMessage(id));
  Panels.item("artifact", artifactTitle, (size, id) => homeArtifact(id));
  Panels.item("agent", (id) => `Agent ${labelOf(id)}`, (size, id) => agentTile(id));
  Panels.item("ancestry", (id) => `Ancestry ${id}`, (size, id) => homeAncestry(id));
  Panels.panel("artifacts/tree", "Artifacts: tree", () => homeTree(() => h("div", {class: "repos"}, treeCards("", true).nodes)));
  Panels.panel("agents/order", "Agents: priority", homeOrder);
  Panels.panel("tasks/operator", "Tasks: Waits on Operator", homeInbox);
  Panels.item("metric", (id, view) => metricTitle(view), (size, id, view) => homeMetric(id, view));
  Panels.capture("resources-hardware", () => resourcePin("hardware"));
  Panels.capture("resources-tokens", () => resourcePin("tokens"));
  Panels.capture("resources-combined", () => resourcePin("combined"));

  const HOME_TREE = 30000;
  const HOME_METRICS = {hardware: "Hardware", tokens: "Tokens", combined: "Combined"};
  const homeMetricView = (view) => Boolean(view) && Object.hasOwn(HOME_METRICS, view.chart) && (view.shown === null || Array.isArray(view.shown));
  const seriesName = (id) => Panels.raw(id).slice(Panels.raw(id).indexOf(":") + 1);

  function homeOrder() {
    const order = state.agent_order;
    return order.length ? h("ol", {class: "order-list home-order"}, order.map((name, index) => h("li", {"data-name": name}, h("span", {class: "rank"}, `${index + 1}.`), face(name, false), person(name))))
      : h("p", {class: "muted"}, "No agent with an office or an open task.");
  }

  function homeInbox() {
    const items = visibleInbox();
    return items.length ? h("ol", {class: "home-inbox"}, items.map((item) => h("li", {class: `k-${item.kind}`, "data-wait": keyOf(item)},
      h("div", {class: "msg-meta"}, when(item.ts), pill(ITEM_LABELS[item.kind], KIND_TONES[item.kind]), item.agent ? [face(item.agent, false), person(item.agent)] : null),
      inboxHeadline(item),
      h("div", {class: "item-actions line-actions"}, actionsFor(item))))) : emptyState("All done", "Nothing is waiting for you right now.");
  }

  function metricTitle(view) {
    if (!homeMetricView(view)) {
      return "Metric";
    }
    const mode = view.chart !== "hardware" && view.tokens === "accumulated" ? " (accumulated)" : "";
    const names = view.shown === null ? "all series" : view.shown.length > 3 ? `${view.shown.length} series` : view.shown.map(seriesName).join(", ") || "no series";
    return `${HOME_METRICS[view.chart]}${mode}: ${names}`;
  }

  function homeMetric(id, view) {
    if (!homeMetricView(view)) {
      return null;
    }
    homeFetch("resources", () => (resourceView.data === null || resourcesStale() ? fetchResources() : null));
    const key = `metric:${id}`;
    const host = homeView.hosts.get(key) || h("div", {class: "home-metric", "data-chart": view.chart}, h("div", {class: "legend-chips"}), h("div", {class: "res-plot"}));
    homeView.hosts.set(key, host);
    window.setTimeout(() => host.isConnected && drawMetric(host, view), 0);
    return host;
  }

  function drawMetric(host, view) {
    const [legend, plot] = host.children;
    if (resourceView.data === null) {
      plot.replaceChildren(homeWait("Loading …"));
      return;
    }
    const box = plot.getBoundingClientRect();
    const drawn = metricChart(view, {width: Math.round(box.width), height: Math.round(box.height)});
    plot.replaceChildren(...(drawn.svg ? [drawn.svg] : []));
    legend.replaceChildren(...drawn.series.map((line) => h("span", {class: `legend-chip ${line.tone}`, "data-series": line.id}, line.label)));
  }

  const HOME_RETRY = 150;
  const HOME_TRIES = 60;
  const HOME_LINKS = {"radio-log": "#stream/radio", "agents/order": "#agents/hierarchy?open=panel:agents/order"};
  const HOME_SCREENS = {task: "#tasks/list", message: "#stream", artifact: "#artifacts/orbit", agent: "#agents/orbit", ancestry: "#artifacts/tree", metric: "#resources"};
  const homeItemOf = (item) => [...document.querySelectorAll("#main [data-item]")].find((node) => node.dataset.item === item) || null;

  /**
   * @param pin - a Home pin.
   * @returns the hash of the full view of its panel or item: the panel's own tab and view, or the item's tab and view
   * with ?open=<pin key>; null for a kind without a full view.
   */
  function homeLink(pin) {
    if (pin.kind === Panels.PANEL) {
      return Object.hasOwn(HOME_LINKS, pin.id) ? HOME_LINKS[pin.id] : `#${pin.id}`;
    }
    return Object.hasOwn(HOME_SCREENS, pin.kind) ? `${HOME_SCREENS[pin.kind]}?open=${Panels.keyOf(pin)}` : null;
  }

  function homeOpenPanel(id) {
    const found = document.querySelector(`#main [data-panel="${id}"]`);
    if (found) {
      found.scrollIntoView({block: "start"});
      const title = found.querySelector('[tabindex="-1"]');
      if (title) {
        title.focus({preventScroll: true});
      }
    }
    return Boolean(found);
  }

  function homeOpenMessage(key) {
    const entry = homeEntry(key);
    if (entry) {
      openPopup("Message", [popupHead(icon(Nav.ICONS.stream), "Message", h("span", {class: "muted"}, when(entry.ts))),
        h("div", {class: "popup-body"}, h("ol", {class: "feed"}, eventRow(entry)))], () => homeItemOf(`message:${key}`));
    }
    return entry !== undefined;
  }

  function homeOpenArtifact(ref) {
    const node = artifactNode(ref);
    if (!node) {
      return Boolean(tree.model);
    }
    if (node.repo && node.repo !== art.repo) {
      art.repo = node.repo;
      drawArtifacts();
    }
    artSelect(node.id);
    return true;
  }

  function homeOpenAncestry(path) {
    if (!tree.data || tree.busy || !tree.dom || tree.dom.view !== "tree") {
      return false;
    }
    tree.open.add(path);
    drawArtifacts();
    const frame = homeItemOf(`ancestry:${path}`);
    if (frame) {
      frame.scrollIntoView({block: "center"});
    }
    return true;
  }

  function homeOpenMetric(id) {
    const pin = homePins().find((entry) => entry.kind === "metric" && entry.id === id);
    if (!pin || !homeMetricView(pin.view)) {
      return true;
    }
    if (!resourceRestore(pin.view)) {
      return false;
    }
    const panel = document.querySelector(`#main [data-panel="resources-${pin.view.chart}"]`);
    if (panel) {
      panel.scrollIntoView({block: "nearest"});
    }
    return true;
  }

  const HOME_OPENERS = {
    panel: homeOpenPanel,
    task: (id) => {
      taskSheet(id);
      return true;
    },
    message: homeOpenMessage,
    artifact: homeOpenArtifact,
    agent: (key) => {
      openAgent(key, pickOf(key));
      return true;
    },
    ancestry: homeOpenAncestry,
    metric: (raw, id) => homeOpenMetric(id),
  };

  /**
   * @param open - the pin key a hash names after ?open=, such as agent:s1 or panel:agents/order.
   * @param screen - the screen the hash shows.
   * @param tries - how many more times to wait HOME_RETRY ms for data the item needs, such as the tree or the samples.
   */
  function homeOpen(open, screen, tries) {
    const cut = open.indexOf(":");
    const kind = open.slice(0, cut);
    const id = open.slice(cut + 1);
    if (cut < 1 || !Object.hasOwn(HOME_OPENERS, kind) || !Panels.ID.test(id) || ui.screen !== screen) {
      return;
    }
    if (!HOME_OPENERS[kind](kind === Panels.PANEL ? id : Panels.raw(id), id) && tries > 0) {
      window.setTimeout(() => homeOpen(open, screen, tries - 1), HOME_RETRY);
    }
  }

  function homeRefused(why) {
    homeView.pins = homeStore.read();
    drawHome();
    homeView.mark();
    toast("Home not saved", [why], false);
  }

  function homeSave(change) {
    const done = homeStore.change(change);
    homeView.pins = homeStore.read();
    drawHome();
    homeView.mark();
    return done.then((stored) => {
      if (stored === false) {
        homeRefused(homeStore.error() || "The view store refused the layout.");
      }
      return stored !== false;
    }, (error) => {
      homeRefused(String(error.message || error));
      return false;
    });
  }

  function homeRefusal(refused, holder, title) {
    if (refused === "full") {
      toast("Home is full", [`At most ${Panels.MAX} pins: unpin one before you pin ${title}.`], false);
    } else if (refused === "group") {
      const other = Panels.lookup(holder.kind, holder.id);
      toast("One 3D tile at a time", [`Home already holds ${other ? other.title : holder.id}: unpin it before you pin ${title}.`], false);
    }
  }

  function homePress(kind, id, title, view) {
    homeView.touched = true;
    if (Panels.has(homePins(), kind, id)) {
      homeSave((pins) => Panels.remove(pins, kind, id));
      return;
    }
    const {refused, holder} = Panels.add(homePins(), kind, id, view);
    if (refused) {
      homeRefusal(refused, holder, title);
      return;
    }
    homeSave((pins) => Panels.add(pins, kind, id, view).pins).then((stored) => {
      const now = homeStore.read();
      if (stored && !Panels.has(now, kind, id)) {
        const late = Panels.add(now, kind, id, view);
        homeRefusal(late.refused, late.holder, title);
      }
    });
  }

  function homeUnpin(key) {
    homeView.touched = true;
    homeSave((pins) => pins.filter((pin) => Panels.keyOf(pin) !== key));
  }

  function homeSpan(tile, size) {
    tile.style.setProperty("--w", String(size.w));
    tile.style.setProperty("--h", String(size.h));
    tile.dataset.w = String(size.w);
    tile.dataset.h = String(size.h);
  }

  function homeGrab(event, key, mode) {
    if (event.button !== 0 || homeIndex(key) < 0) {
      return;
    }
    event.preventDefault();
    const pin = homePins()[homeIndex(key)];
    const grid = homeView.dom.grid;
    const look = getComputedStyle(grid);
    const gap = parseFloat(look.columnGap) || 0;
    const column = (grid.clientWidth - gap * (Panels.SPAN - 1)) / Panels.SPAN + gap;
    const row = (parseFloat(look.gridAutoRows) || 1) + (parseFloat(look.rowGap) || 0);
    homeView.drag = {mode, key, x: event.clientX, y: event.clientY, start: {w: pin.w, h: pin.h}, next: {w: pin.w, h: pin.h}, column, row, over: null};
    homeView.tiles.get(key).classList.add("dragging");
  }

  function homeDragMove(event) {
    const drag = homeView.drag;
    if (!drag) {
      return;
    }
    const tile = homeView.tiles.get(drag.key);
    if (drag.mode === "size") {
      drag.next = Panels.stretch(drag.start, event.clientX - drag.x, event.clientY - drag.y, drag.column, drag.row);
      homeSpan(tile, drag.next);
      return;
    }
    const under = document.elementFromPoint(event.clientX, event.clientY);
    const into = under ? under.closest(".home-tile") : null;
    drag.over = into && into !== tile ? into.dataset.pin : null;
    homeView.tiles.forEach((other) => other.classList.toggle("drop", other.dataset.pin === drag.over));
  }

  function homeDragEnd() {
    const drag = homeView.drag;
    if (!drag) {
      return;
    }
    homeView.drag = null;
    homeView.tiles.forEach((tile) => tile.classList.remove("drop", "dragging"));
    const {key, next, over} = drag;
    if (drag.mode === "size" && (next.w !== drag.start.w || next.h !== drag.start.h)) {
      homeSave((pins) => Panels.resizeKey(pins, key, next.w, next.h));
    } else if (drag.mode === "move" && over) {
      homeSave((pins) => Panels.placeKey(pins, key, over));
    } else {
      drawHome();
    }
  }

  function homeKeys(event, key) {
    const steps = {ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1};
    if (event.target !== event.currentTarget || !Object.hasOwn(steps, event.key) || event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }
    event.preventDefault();
    homeSave((pins) => Panels.moveKey(pins, key, steps[event.key]));
  }

  function homeSizeKeys(event, key) {
    const steps = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
    if (!Object.hasOwn(steps, event.key)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const [dw, dh] = steps[event.key];
    homeSave((pins) => Panels.resizeBy(pins, key, dw, dh));
  }

  function homeGone(pin, key) {
    return h("div", {class: "home-gone"}, h("strong", {class: "home-gone-word"}, "gone"),
      h("p", {class: "muted"}, `This ${pin.kind} no longer exists: ${Panels.raw(pin.id).replace(/\u0000/g, " ")}`),
      btn("Unpin", "btn small danger home-gone-unpin", () => homeUnpin(key)));
  }

  function homeTile(key) {
    const title = h("h3", {class: "home-title"});
    const body = h("div", {class: "home-body"});
    const grip = iconBtn("bi-grip-vertical", "Move", "btn small ghost home-grip", null, "Move: drag to another tile, or focus the tile and press the arrow keys");
    const handle = iconBtn("bi-arrow-down-right", "Resize", "btn small ghost home-resize", null, "Resize: drag, or the arrow keys, 1 to 12 columns wide and rows high");
    const open = h("a", {class: "btn small ghost icon-only home-open", "aria-label": "Open", hidden: true}, icon("bi-arrows-angle-expand"));
    const tile = h("article", {class: "home-tile", tabindex: 0, role: "listitem", "data-pin": key, on: {keydown: (event) => homeKeys(event, key)}},
      h("header", {class: "home-head"}, grip, title, open, iconBtn("bi-x-lg", "Unpin", "btn small ghost home-unpin", () => homeUnpin(key), "Unpin: remove the tile from Home")), body, handle);
    grip.addEventListener("pointerdown", (event) => homeGrab(event, key, "move"));
    handle.addEventListener("pointerdown", (event) => homeGrab(event, key, "size"));
    handle.addEventListener("keydown", (event) => homeSizeKeys(event, key));
    homeView.tiles.set(key, tile);
    return tile;
  }

  function homeOpenLink(open, link, name) {
    open.hidden = !link;
    if (link) {
      open.setAttribute("href", link);
      open.setAttribute("title", `Open: show ${name} in full view`);
    } else {
      open.removeAttribute("href");
    }
  }

  function homeContent(entry, pin) {
    try {
      return entry.render({w: pin.w, h: pin.h});
    } catch (error) {
      return h("p", {class: "muted home-error"}, `Not drawable: ${error.message || error}`);
    }
  }

  function homeFill(tile, pin, index, count) {
    const key = Panels.keyOf(pin);
    const entry = Panels.lookup(pin.kind, pin.id, pin.view);
    const content = entry ? homeContent(entry, pin) : null;
    const name = entry ? entry.title : `${pin.kind} ${pin.id}`;
    tile.classList.toggle("gone", !content);
    tile.dataset.kind = pin.kind;
    tile.dataset.id = pin.id;
    tile.setAttribute("aria-label", `${name}, ${pin.w} by ${pin.h}, tile ${index + 1} of ${count}`);
    homeSpan(tile, pin);
    tile.querySelector(".home-title").textContent = name;
    homeOpenLink(tile.querySelector(".home-open"), content ? homeLink(pin) : null, name);
    const body = tile.querySelector(".home-body");
    const shown = content || homeGone(pin, key);
    if (body.childNodes.length !== 1 || body.firstChild !== shown) {
      body.replaceChildren(shown);
    }
  }

  function drawHome() {
    const dom = homeView.dom;
    if (!dom || !dom.grid.isConnected) {
      homeView.dom = null;
      return;
    }
    if (homeView.drag) {
      return;
    }
    const pins = homePins();
    const keys = new Set(pins.map(Panels.keyOf));
    for (const [key, tile] of homeView.tiles) {
      if (!keys.has(key)) {
        tile.remove();
        homeView.tiles.delete(key);
      }
    }
    const focused = document.activeElement;
    pins.forEach((pin, index) => {
      const key = Panels.keyOf(pin);
      const tile = homeView.tiles.get(key) || homeTile(key);
      homeFill(tile, pin, index, pins.length);
      if (dom.grid.children[index] !== tile) {
        dom.grid.insertBefore(tile, dom.grid.children[index] || null);
      }
    });
    if (focused instanceof HTMLElement && focused.isConnected && document.activeElement !== focused) {
      focused.focus();
    }
    dom.empty.hidden = pins.length > 0;
  }

  function homeScreen() {
    const grid = h("div", {class: "home-grid", role: "list", "aria-label": "Pinned panels and items"});
    const empty = emptyState("Nothing pinned yet", "Press the star on any panel or item to pin it here; pins, sizes and order are kept for every browser.");
    homeView.dom = {grid, empty};
    homeView.tiles = new Map();
    return h("div", {class: "home"}, empty, grid);
  }

  function homeBoot() {
    homeView.pins = homeStore.read();
    const opened = homePins().length;
    homeStore.watch((pins) => {
      homeView.pins = pins;
      if (!homeView.touched && !opened && pins.length && ui.screen === "stream" && !window.location.hash.replace(/^#/, "")) {
        apply();
        return;
      }
      drawHome();
      homeView.mark();
    });
    homeView.mark = Panels.decorate(document.body, {pinned: (kind, id) => Panels.has(homePins(), kind, id), press: homePress, marks: HOME_MARKS});
    window.addEventListener("pointermove", homeDragMove);
    window.addEventListener("pointerup", homeDragEnd);
    window.addEventListener("pointercancel", homeDragEnd);
  }
