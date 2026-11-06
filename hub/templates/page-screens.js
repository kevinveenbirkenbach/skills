  const nav = document.getElementById("tabs");
  const screenButtons = new Map(SCREENS.map(([id, label], index) => {
    const button = h("button", {type: "button", role: "tab", id: `tab-${id}`, "aria-controls": "main", title: `${label} (Taste ${index + 1})`, on: {click: () => go(id, null)}}, label);
    nav.append(button);
    return [id, button];
  }));

  function measure() {
    document.documentElement.style.setProperty("--head", `${document.getElementById("head").offsetHeight}px`);
  }

  function go(screen, sub) {
    const hash = screen === "graph" ? `#graph/${sub || ui.graph}` : `#${screen}`;
    if (window.location.hash === hash) {
      apply();
    } else {
      window.location.hash = hash;
    }
  }

  function apply() {
    const [screen, sub] = decodeURIComponent(window.location.hash.slice(1)).split("/");
    ui.screen = SCREENS.some(([id]) => id === screen) ? screen : "stream";
    if (GRAPHS.some(([id]) => id === sub)) {
      ui.graph = sub;
    }
    if (document.startViewTransition && drawn.screen && !calm.matches) {
      document.startViewTransition(() => render(true));
    } else {
      render(true);
    }
  }

  function signature() {
    return JSON.stringify(ui.screen === "graph" ? [ui.graph, space.views.graph.axis] : []);
  }

  function render(force) {
    if (ui.node !== null && !state.graph.nodes.some((node) => node.id === ui.node)) {
      ui.node = null;
    }
    for (const [id, button] of screenButtons) {
      button.setAttribute("aria-selected", String(ui.screen === id));
    }
    const sig = signature();
    if (force || drawn.screen !== ui.screen || drawn.sig !== sig) {
      graphDom = null;
      stream.dom = null;
      tree.dom = null;
      const main = document.getElementById("main");
      main.setAttribute("aria-labelledby", `tab-${ui.screen}`);
      main.replaceChildren({stream: streamScreen, graph: graphScreen, tree: treeScreen}[ui.screen]());
      drawn.screen = ui.screen;
      drawn.sig = sig;
    }
    stage();
    drawSide();
    drawInbox();
    drawStatus();
    tick();
  }

  function drawStatus() {
    const alarms = alarmRows().length;
    const fresh = state.now - ACTIVE;
    const agents = new Set(state.claims.filter((claim) => claim.beat !== null && claim.beat >= fresh).map((claim) => claim.agent)).size;
    const jobs = state.jobs.filter((job) => job.status === "queued" || job.status === "running").length;
    const [mode] = NIGHT[state.night] || [state.night];
    const waiting = waitingCount();
    const box = (value, label, tone) => h("div", {class: `stat-box${tone ? ` ${tone}` : ""}`}, h("span", {class: "num"}, String(value)), h("span", {class: "lbl"}, label));
    document.getElementById("status").replaceChildren(
      box(waiting, "wartet auf dich", waiting ? "urgent" : ""),
      box(alarms, "Mayday", alarms ? "alarm" : ""),
      box(agents, "Agenten aktiv", ""),
      box(jobs, "Runner", ""),
      box(mode, "Modus", ""));
    const badge = document.getElementById("inbox-count");
    badge.textContent = String(waiting);
    badge.className = `badge${alarms ? " alarm" : waiting ? " urgent" : ""}`;
    document.title = `${waiting ? `(${waiting}) ` : ""}kvb-hub`;
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
