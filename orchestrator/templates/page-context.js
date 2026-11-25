  const ctxMenu = {node: null, back: null};
  const CTX_FIELDS = ["INPUT", "TEXTAREA", "SELECT"];
  const CTX_GAP = 8;
  const CTX_MODIFIERS = ["Shift", "Control", "Alt", "Meta"];
  const CTX_OPENS = {task: "Open task", message: "Open message", artifact: "Open artifact"};
  const ctxAttr = (...names) => (node) => names.map((name) => node.getAttribute(name)).find(Boolean) || null;
  const ctxField = (node) => Boolean(node.isContentEditable) || CTX_FIELDS.includes(node.tagName);
  const ctxInside = (node) => Boolean(ctxMenu.node) && ctxMenu.node.contains(node);
  const ctxCopyItem = (label, text) => ({label, hint: text, run: () => ctxCopy(text)});

  function ctxAgentOf(node) {
    const raw = ctxAttr("data-agent", "data-face", "data-name", "data-session")(node);
    return raw && raw !== HUMAN ? agentKey(raw) : null;
  }

  function ctxPinOf(node) {
    return node.matches(Panels.HOSTS) ? Panels.targetOf(node) : null;
  }

  const ctxPinEntry = (target) => (target.id && !target.refused ? Panels.lookup(target.kind, target.id, target.view) : null);
  const ctxEntryOf = (ref) => state.inbox.find((entry) => keyOf(entry) === ref) || null;
  const ctxArtifactOf = (id) => (tree.model ? tree.model.byId.get(id) || null : null);

  function ctxTaskItems(node, id) {
    const known = state.tasks.some((row) => row.task === id);
    return [...(known ? [{label: "Open task", hint: id, run: () => taskSheet(id)}] : []), ctxCopyItem("Copy task id", id)];
  }

  function ctxAgentItems(node, key) {
    return [ctxCopyItem("Copy name", nameOf(key))];
  }

  function ctxBranchItems(node, name) {
    const ref = `branch:${node.getAttribute("data-repo")}\u0000${name}`;
    const open = ctxArtifactOf(ref) ? [{label: "Open branch", hint: name, run: () => artSelect(ref)}] : [];
    return [...open, ctxCopyItem("Copy branch name", name), {label: "Explain", hint: "what each mark of a branch means", run: () => openSheet("Explain", glossarySections(), false)}];
  }

  function ctxPathItems(node, path) {
    return [...feedbackItems(node), ...(path === "-" ? [] : [ctxCopyItem("Copy path", path)])];
  }

  function ctxEntryItems(node, ref) {
    const item = ctxEntryOf(ref);
    return item ? [{label: "Open entry", hint: item.title, run: () => openItem(item)}, ctxCopyItem("Copy id", item.id)] : [];
  }

  function ctxPickItems(node, id) {
    const found = ctxArtifactOf(id);
    if (found) {
      return [{label: "Open artifact", hint: found.label, run: () => artSelect(id)}];
    }
    const sub = state.graph.nodes.find((entry) => entry.id === id && entry.kind === "subagent");
    return sub ? [{label: "Open parent agent", hint: labelOf(sub.parent), run: () => select(id)}] : [];
  }

  function ctxPickTitle(id) {
    const found = ctxArtifactOf(id) || state.graph.nodes.find((entry) => entry.id === id);
    return found ? found.label : id;
  }

  function ctxPinItems(node, target) {
    const entry = ctxPinEntry(target);
    if (!entry) {
      return [];
    }
    const opens = Object.hasOwn(CTX_OPENS, target.kind) ? [{label: CTX_OPENS[target.kind], hint: entry.title, run: () => HOME_OPENERS[target.kind](Panels.raw(target.id), target.id)}] : [];
    const pinned = Panels.has(homePins(), target.kind, target.id);
    return [...opens, {label: pinned ? "Unpin from Home" : "Pin to Home", hint: entry.title, run: () => homePress(target.kind, target.id, entry.title, target.view)}];
  }

  function ctxTileItems(node, key) {
    const hint = `${node.querySelector(".home-title").textContent}: zoom its content`;
    return [
      {label: "Zoom in", hint: `${hint} (+)`, run: () => homeZoomBy(key, 1)},
      {label: "Zoom out", hint: `${hint} (-)`, run: () => homeZoomBy(key, -1)},
      {label: `Reset zoom (${homeZoom(key)} %)`, hint: `${hint} (0)`, run: () => homeZoomBy(key, 0)},
    ];
  }

  const CTX_KINDS = [
    {kind: "task", id: ctxAttr("data-task"), title: (id) => `Task ${id}`, items: ctxTaskItems},
    {kind: "agent", id: ctxAgentOf, title: (key) => nameOf(key), items: ctxAgentItems},
    {kind: "branch", id: ctxAttr("data-branch"), title: (name) => `Branch ${name}`, items: ctxBranchItems},
    {kind: "path", id: ctxAttr("data-path"), title: (path) => path, items: ctxPathItems},
    {kind: "entry", id: ctxAttr("data-ref"), title: (ref) => ctxEntryOf(ref).title, items: ctxEntryItems},
    {kind: "rule", id: ctxAttr("data-rule", "data-entry"), title: (id) => `Rule ${id}`, items: (node, id) => [ctxCopyItem("Copy rule", id)]},
    {kind: "pick", id: ctxAttr("data-pick"), title: ctxPickTitle, items: ctxPickItems},
    {kind: "pin", id: ctxPinOf, title: (target) => ctxPinEntry(target).title, items: ctxPinItems},
    {kind: "tile", id: (node) => (node.matches(".home-tile[data-pin]") ? node.dataset.pin : null), title: (key) => `Tile ${key}`, items: ctxTileItems},
  ];

  /**
   * @param target - the element a right-click or the menu key hit.
   * @returns [{kind, id, node, entry}]: per kind of CTX_KINDS the nearest marked element from target up, nearest first.
   */
  function ctxFound(target) {
    const found = [];
    for (let node = target; node; node = node.parentElement) {
      for (const entry of CTX_KINDS.filter((kind) => !found.some((seen) => seen.kind === kind.kind))) {
        const id = entry.id(node);
        if (id) {
          found.push({kind: entry.kind, id, node, entry});
        }
      }
    }
    return found;
  }

  function ctxOwn(found, items) {
    const groups = found.map((seen) => ({seen, items: items.filter((item) => item.scope === seen.kind && item.id === seen.id)})).filter((group) => group.items.length);
    const flat = groups.flatMap((group) => group.items);
    return {title: groups.length ? groups[0].seen.entry.title(groups[0].seen.id) : "", items: flat.filter((item, index) => flat.findIndex((other) => other.label === item.label) === index)};
  }

  /**
   * @param target - the element the menu is for.
   * @returns [{scope, title, items}]: the element's own items, then the current tab's, then the general ones; empty
   * sections left out.
   */
  function ctxSections(target) {
    const found = ctxFound(target);
    const provided = found.flatMap((seen) => seen.entry.items(seen.node, seen.id).map((item) => ({...item, scope: seen.kind, id: seen.id})));
    const items = [...paletteItems(), ...provided];
    const own = ctxOwn(found, items);
    const tab = Nav.TABS.find(([id]) => id === Nav.tabOf(ui.screen));
    return [
      {scope: "element", title: own.title, items: own.items},
      ...(tab ? [{scope: tab[0], title: tab[1], items: items.filter((item) => item.scope === tab[0])}] : []),
      {scope: "general", title: "General", items: items.filter((item) => item.scope === "general")},
    ].filter((section) => section.items.length);
  }

  async function ctxCopy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied", [revealed(text)], true);
    } catch {
      toast("Not copied", ["The browser refused the clipboard."], false);
    }
  }

  function ctxNode() {
    if (!ctxMenu.node) {
      ctxMenu.node = h("div", {class: "ctx-menu", role: "menu", "aria-label": "Context menu", tabindex: -1, hidden: true, on: {keydown: ctxKeys}});
      document.body.append(ctxMenu.node);
    }
    return ctxMenu.node;
  }

  function ctxItem(item) {
    return h("button", {type: "button", role: "menuitem", tabindex: -1, class: "ctx-item", title: revealed(item.hint), on: {click: () => ctxRun(item)}},
      item.face ? face(item.face, false) : null, h("span", {class: "ctx-label"}, revealed(item.label)), h("span", {class: "muted"}, revealed(item.hint)));
  }

  function ctxGroup(section, index) {
    return [index ? h("div", {role: "separator", class: "ctx-rule"}) : null,
      h("div", {role: "group", class: "ctx-group", "aria-label": revealed(section.title), "data-scope": section.scope}, h("div", {class: "ctx-head", "aria-hidden": "true"}, revealed(section.title)), section.items.map(ctxItem))];
  }

  function ctxPlace(node, at) {
    node.style.left = "0px";
    node.style.top = "0px";
    const box = node.getBoundingClientRect();
    const below = at.y + box.height + CTX_GAP <= window.innerHeight;
    node.style.left = `${Math.max(CTX_GAP, Math.min(at.x, window.innerWidth - box.width - CTX_GAP))}px`;
    node.style.top = `${Math.max(CTX_GAP, Math.min(below ? at.y : at.y - box.height, window.innerHeight - box.height - CTX_GAP))}px`;
  }

  /**
   * @param sections - what ctxSections gives.
   * @param at - {x, y}, the viewport point the menu opens at; it moves inside the viewport when it would run past it.
   */
  function ctxShow(sections, at) {
    const node = ctxNode();
    node.replaceChildren(...sections.flatMap(ctxGroup).filter(Boolean));
    node.hidden = false;
    ctxPlace(node, at);
    const first = node.querySelector('[role="menuitem"]');
    if (first) {
      first.focus({preventScroll: true});
    }
  }

  function ctxOpen(target, at) {
    closeMenus(null);
    ctxMenu.back = document.activeElement;
    diffView.hit = target;
    ctxShow(ctxSections(target), at);
  }

  function ctxClose(restore) {
    if (!ctxMenu.node || ctxMenu.node.hidden) {
      return;
    }
    const back = ctxMenu.back;
    ctxMenu.back = null;
    ctxMenu.node.hidden = true;
    ctxMenu.node.replaceChildren();
    if (restore && back && back.isConnected && typeof back.focus === "function") {
      back.focus({preventScroll: true});
    }
  }

  function ctxRun(item) {
    ctxClose(true);
    item.run();
  }

  /**
   * @param keep - the menu a click landed in, as closeMenus gets it; the context menu stays open when it is that menu.
   */
  function ctxDismiss(keep) {
    if (ctxMenu.node && ctxMenu.node !== keep) {
      ctxClose(ctxMenu.node.contains(document.activeElement));
    }
  }

  function ctxKeys(event) {
    const items = [...ctxMenu.node.querySelectorAll('[role="menuitem"]')];
    const at = items.indexOf(document.activeElement);
    const moves = {ArrowDown: at + 1, ArrowUp: Math.max(at, 0) - 1, Home: 0, End: items.length - 1};
    if (Object.hasOwn(moves, event.key)) {
      items[(moves[event.key] + items.length) % items.length].focus();
    } else if (event.key === "Enter" || event.key === " ") {
      items[Math.max(at, 0)].click();
    } else if (CTX_MODIFIERS.includes(event.key)) {
      return;
    } else {
      ctxClose(true);
    }
    event.preventDefault();
    event.stopPropagation();
  }

  function ctxContextMenu(event) {
    const target = event.target;
    if (!(target instanceof Element) || event.defaultPrevented) {
      return;
    }
    if (ctxInside(target)) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey || ctxField(target)) {
      return;
    }
    event.preventDefault();
    ctxOpen(target, {x: event.clientX, y: event.clientY});
  }

  function ctxKeydown(event) {
    const pressed = event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey);
    const target = document.activeElement;
    if (!pressed || event.ctrlKey || event.altKey || event.metaKey || !(target instanceof Element) || ctxField(target) || ctxInside(target)) {
      return;
    }
    event.preventDefault();
    const box = target.getBoundingClientRect();
    ctxOpen(target, {x: box.left, y: box.bottom});
  }
