  const navButtons = new Map();

  function tabButton(id, label, hint) {
    const badge = Object.hasOwn(state.badges, id) ? h("span", {class: "badge", hidden: true}) : null;
    const button = h("button", {type: "button", id: `tab-${id}`, class: "icon-only", "aria-controls": "main", ...named(label, hint ? `${label} (${hint})` : label), on: {click: () => go(id, null)}}, icon(Nav.ICONS[id]), badge);
    navButtons.set(id, {button, badge});
    return button;
  }

  document.getElementById("tabs").append(...Nav.TABS.map(([id, label], index) => h("div", {class: "tab-group"},
    tabButton(id, label, `Taste ${index + 1}`),
    Nav.SUBS[id] ? h("div", {class: "subtabs"}, Nav.SUBS[id].map(([sub, name]) => tabButton(sub, name, ""))) : null)));

  function measure() {
    document.documentElement.style.setProperty("--head", `${document.getElementById("head").offsetHeight}px`);
  }

  function go(screen, view) {
    const hash = Nav.hashOf(screen, view || ui.views[screen] || null);
    if (window.location.hash === hash) {
      apply();
    } else {
      window.location.hash = hash;
    }
  }

  function apply() {
    const route = Nav.route(window.location.hash);
    if (route.redirect) {
      window.history.replaceState(null, "", route.redirect);
    }
    ui.screen = route.screen;
    if (route.view) {
      ui.views[route.screen] = route.view;
    }
    if (document.startViewTransition && drawn.screen && !calm.matches) {
      document.startViewTransition(() => render(true));
    } else {
      render(true);
    }
  }

  function signature() {
    if (ui.screen === "agents") {
      return JSON.stringify([ui.views.agents]);
    }
    return JSON.stringify(ui.screen === "artifacts" ? [ui.views.artifacts] : ui.screen === "rules" ? state.rules : []);
  }

  function screenOf() {
    return {stream: streamScreen, inbox: inboxScreen, rules: rulesScreen, agents: agentsScreen, artifacts: artifactsScreen}[ui.screen]();
  }

  function render(force) {
    if (ui.node !== null && !state.graph.nodes.some((node) => node.id === ui.node)) {
      ui.node = null;
    }
    for (const [id, {button}] of navButtons) {
      button.setAttribute("aria-current", ui.screen === id ? "page" : "false");
    }
    const sig = signature();
    if (force || drawn.screen !== ui.screen || drawn.sig !== sig) {
      graphDom = null;
      stream.dom = null;
      tree.dom = null;
      inboxDom = null;
      inboxSig = "";
      const main = document.getElementById("main");
      main.setAttribute("aria-labelledby", `tab-${ui.screen}`);
      main.replaceChildren(screenOf());
      drawn.screen = ui.screen;
      drawn.sig = sig;
      if (g3.host && !g3.host.isConnected) {
        dispose3d();
      }
    }
    stage();
    drawSide();
    drawSpawn();
    drawHierarchy(force);
    drawToolbar();
    drawInbox();
    drawStatus();
    tick();
  }

  function drawStatus() {
    for (const [id, count] of Object.entries(state.badges)) {
      const {badge} = navButtons.get(id);
      badge.textContent = String(count);
      badge.hidden = count === 0;
      badge.className = `badge${id === "inbox" && count ? " urgent" : ""}`;
    }
    const banner = document.getElementById("mayday");
    const silence = state.silence;
    banner.hidden = !silence;
    banner.replaceChildren(...(silence ? [h("p", {class: "text"}, `MAYDAY · ${dash(silence.by)}: ${silence.text}`), iconBtn("bi-x-octagon", "aufheben", "btn small", () => confirmAct("clear-mayday"), "aufheben: Mayday beenden (radio.py clear)")] : []));
    document.title = `${state.badges.inbox ? `(${state.badges.inbox}) ` : ""}Agent Orchestrator`;
    window.setTimeout(measure, 0);
  }

  function toggleLeitstand() {
    const on = !document.body.classList.contains("leitstand");
    document.body.classList.toggle("leitstand", on);
    if (on && document.documentElement.requestFullscreen && !document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => null);
    }
    if (!on && document.fullscreenElement) {
      document.exitFullscreen().catch(() => null);
    }
    window.setTimeout(measure, 50);
  }
