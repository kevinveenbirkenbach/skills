  const navButtons = new Map();

  function tabButton(id, label, hint) {
    const own = id === "tasks";
    const badge = Object.hasOwn(state.badges, id) ? h(own ? "a" : "span", {class: "badge", hidden: true, href: own ? Nav.hashOf("match", null) : null}) : null;
    const button = h("button", {type: "button", id: `tab-${id}`, class: "icon-only", "aria-controls": "main", ...named(label, hint ? `${label} (${hint})` : label), on: {click: () => go(id, null)}}, icon(Nav.ICONS[id]), own ? null : badge);
    navButtons.set(id, {button, badge});
    return own ? [button, badge] : button;
  }

  document.getElementById("tabs").append(...Nav.TABS.map(([id, label], index) => h("div", {class: "tab-group"},
    tabButton(id, label, `key ${index + 1}`),
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
    const route = Nav.route(window.location.hash, homePins().length);
    if (route.redirect) {
      window.history.replaceState(null, "", route.redirect);
    }
    if (route.spot) {
      openSpot(true);
    }
    ui.screen = route.screen;
    if (route.view) {
      ui.views[route.screen] = route.view;
    }
    const show = () => {
      render(true);
      if (route.open) {
        window.setTimeout(() => homeOpen(route.open, route.screen, HOME_TRIES), 0);
      }
    };
    if (document.startViewTransition && drawn.screen && !calm.matches) {
      document.startViewTransition(show).ready.catch((error) => {
        if (error.name !== "AbortError") {
          throw error;
        }
      });
    } else {
      show();
    }
  }

  function signature() {
    if (ui.screen === "agents") {
      return JSON.stringify([ui.views.agents]);
    }
    return JSON.stringify(ui.screen === "artifacts" || ui.screen === "tasks" ? [ui.views[ui.screen]] : ui.screen === "rules" ? [state.rules, state.schedules] : []);
  }

  function screenOf() {
    return {home: homeScreen, stream: streamScreen, inbox: tasksScreen, match: matchScreen, rules: rulesScreen, agents: agentsScreen, artifacts: artifactsScreen, tasks: tasksScreen, resources: resourcesScreen}[ui.screen]();
  }

  function render(force) {
    for (const [id, {button}] of navButtons) {
      button.setAttribute("aria-current", ui.screen === id || (!navButtons.has(ui.screen) && Nav.tabOf(ui.screen) === id) ? "page" : "false");
    }
    const sig = signature();
    if (force || drawn.screen !== ui.screen || drawn.sig !== sig) {
      graphDom = null;
      stream.dom = null;
      tree.dom = null;
      inboxDom = null;
      inboxSig = "";
      taskView.dom = null;
      matchView.dom = null;
      const main = document.getElementById("main");
      main.setAttribute("aria-labelledby", `tab-${ui.screen}`);
      main.replaceChildren(screenOf());
      const fit = ["tasks", "inbox", "match", "resources"].includes(ui.screen) || (["agents", "artifacts"].includes(ui.screen) && !["tree", "hierarchy"].includes(ui.views[ui.screen]));
      document.body.classList.toggle("fit", fit);
      document.body.classList.toggle("pane", !fit);
      drawn.screen = ui.screen;
      drawn.sig = sig;
      if (g3.host && !g3.host.isConnected) {
        dispose3d();
      }
    }
    stage();
    drawSpawn();
    drawHome();
    drawHierarchy(force);
    drawToolbar();
    drawInbox();
    drawGrant();
    drawRadio();
    drawTasks();
    drawMatch(false);
    drawChoices();
    drawStatus();
    tick();
    placePopup();
  }

  function drawStatus() {
    for (const [id, count] of Object.entries(state.badges)) {
      const {badge} = navButtons.get(id);
      badge.textContent = String(count);
      badge.hidden = count === 0;
      badge.className = `badge${id === "tasks" && count ? " urgent" : ""}`;
      if (badge.tagName === "A") {
        badge.setAttribute("aria-label", `${count} open operator ${count === 1 ? "task" : "tasks"}: open Match`);
      }
    }
    const banner = document.getElementById("mayday");
    const silence = state.silence;
    const alarm = silence ? `MAYDAY · ${dash(silence.by)}: ${silence.text}` : "";
    if (banner.alarm !== alarm) {
      banner.alarm = alarm;
      banner.hidden = !silence;
      banner.replaceChildren(...(silence ? [h("p", {class: "text", title: alarm}, alarm), iconBtn("bi-x-octagon", "cancel", "btn small", () => confirmAct("clear-mayday", []), "cancel: end the mayday (radio.py clear)")] : []));
    }
    drawTitle();
    window.setTimeout(measure, 0);
  }

  function drawTitle() {
    document.title = `${settings.channels.title && state.badges.tasks ? `(${state.badges.tasks}) ` : ""}Agent Orchestrator`;
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
