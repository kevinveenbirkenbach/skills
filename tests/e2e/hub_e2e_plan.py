from __future__ import annotations

from hub_e2e_kit import HELPERS

PLAN_HELPERS = """
  const fits = () => ({tall: document.documentElement.scrollHeight > window.innerHeight, wide: document.documentElement.scrollWidth > window.innerWidth + 1, rows: toolbarRows(), layout: taskLayout()});
  const modes = () => all('#main [aria-label="Estimation"] button').map((button) => [button.dataset.estimation, button.getAttribute("aria-pressed")]);
  const requestShown = () => {
    const button = document.getElementById("request-estimates");
    return button ? !button.hidden && button.getClientRects().length > 0 : null;
  };
  const choose = async (select, value) => {
    select.value = value;
    select.dispatchEvent(new Event("change", {bubbles: true}));
    await sleep(300);
  };
  const fresh = async (shown, prefix) => until(() => all("#toasts .toast").filter((box) => !shown.has(box)).map(text).find((entry) => entry.startsWith(prefix)), 20000);
"""
GANTT = """(async () => {@HELPERS@@PLAN_HELPERS@
  const svg = await until(() => document.querySelector("#main svg.gantt"), 8000);
  if (!svg) {
    return {error: text(document.getElementById("main"))};
  }
  const forecast = document.querySelector('#main select[aria-label="Forecast"]');
  const scroll = document.querySelector("#main .gantt-scroll");
  const marks = () => all("#main svg.gantt [data-forecast]").map((mark) => [mark.dataset.task, mark.dataset.forecast === "true", Number(mark.dataset.start), Number(mark.dataset.end), mark.tagName.toLowerCase()]);
  const found = {
    hash: location.hash,
    forecast: [forecast.value, all("option", forecast).map((option) => [option.value, text(option)])],
    modes: modes(),
    request: requestShown(),
    bars: marks(),
    edges: all("#main svg.gantt path.gantt-edge").map((path) => [path.dataset.kind, path.dataset.from, path.dataset.to, path.getAttribute("marker-end")]),
    hatched: all("#main svg.gantt .gantt-bar.forecast").map((bar) => getComputedStyle(bar).fill.includes("gantt-hatch")),
    inner: Boolean(scroll && scroll.closest(".tasks-body")),
    ...fits(),
  };
  await choose(forecast, "real");
  found.real = marks().filter(([, hatched]) => hatched).length;
  await choose(forecast, "points");
  found.pointsOnly = marks().filter(([, hatched]) => hatched).map(([task, , start, end, tag]) => [task, end - start, tag]);
  await choose(forecast, "always");
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
BURN = """(async () => {@HELPERS@@PLAN_HELPERS@
  const svg = await until(() => document.querySelector("#main svg.burn"), 8000);
  if (!svg) {
    return {error: text(document.getElementById("main"))};
  }
  const scope = document.querySelector('#main select[aria-label="Scope"]');
  const series = () => all("#main svg.burn path.burn-line").map((path) => [path.dataset.series, Number(path.dataset.last)]);
  const found = {hash: location.hash, modes: modes(), request: requestShown(), scope: [scope.value, all("option", scope).map((option) => option.value)], series: series(), ...fits()};
  await choose(scope, "agent:Docs");
  found.agent = series();
  await choose(scope, "all");
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
POINTS_ON = """(async () => {@HELPERS@@PLAN_HELPERS@
  const before = {modes: modes(), request: requestShown()};
  all('#main [aria-label="Estimation"] button').find((button) => button.dataset.estimation === "points").click();
  const shown = await until(() => requestShown(), 8000);
  return {before, modes: modes(), request: Boolean(shown), ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
REQUEST = """(async () => {@HELPERS@@PLAN_HELPERS@
  const svg = await until(() => document.querySelector("#main svg.burn") && requestShown(), 8000);
  if (!svg) {
    return {error: text(document.getElementById("main")), modes: modes()};
  }
  const series = all("#main svg.burn path.burn-line").map((path) => [path.dataset.series, Number(path.dataset.last)]);
  const shown = new Set(all("#toasts .toast"));
  document.getElementById("request-estimates").click();
  const toast = await fresh(shown, "Request estimates");
  return {modes: modes(), series, toast, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
BULK = """(async () => {@HELPERS@@PLAN_HELPERS@
  const list = await until(() => all("#main .task-row").length && document.getElementById("bulk-value"), 8000);
  if (!list) {
    return {error: text(document.getElementById("main"))};
  }
  let asked = 0;
  const get = navigator.credentials.get.bind(navigator.credentials);
  navigator.credentials.get = (options) => {
    asked += 1;
    return @SIGNS@ ? get(options) : Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (["/api/sign", "/api/tasks"].includes(String(path))) {
      const body = JSON.parse(init.body);
      posted.push([String(path), Object.keys(body).sort(), body.items.map((item) => [item.id, item.argv.join(" ")])]);
    }
    return send(path, init);
  };
  const rows = () => all("#main .task-row").map((row) => row.dataset.task);
  const sort = document.querySelector('#main select[aria-label="Sort"]');
  const direction = document.querySelector("#main button[data-direction]");
  const found = {sorts: all("option", sort).map((option) => option.value), prio: rows()};
  await choose(sort, "status");
  found.status = rows();
  direction.click();
  await sleep(300);
  found.statusDown = [rows(), name(direction)];
  direction.click();
  await choose(sort, "prio");
  found.picks = all("#main .task-row input.task-pick").map((box) => box.closest(".task-row").dataset.task);
  for (const task of ["work/next", "work/child"]) {
    all("#main .task-row").find((row) => row.dataset.task === task).querySelector("input.task-pick").click();
  }
  const button = document.getElementById("bulk-value");
  found.armed = [button.disabled, text(button.querySelector(".count"))];
  await choose(document.querySelector('#main select[aria-label="Business value of the selection"]'), "@VALUE@");
  const shown = new Set(all("#toasts .toast"));
  button.click();
  found.toast = await fresh(shown, "Business value @VALUE@ for 2 tasks");
  found.asked = asked;
  found.posted = posted;
  found.after = [button.disabled, all("#main .task-row input.task-pick:checked").length];
  Object.assign(found, fits());
  all('#main [aria-label="Estimation"] button').find((entry) => entry.dataset.estimation === "none").click();
  found.reset = Boolean(await until(() => requestShown() === false, 8000));
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
ETA_LIST = """(async () => {@HELPERS@@PLAN_HELPERS@
  const list = await until(() => all("#main .task-row .task-eta").length >= 8, 8000);
  if (!list) {
    return {error: text(document.getElementById("main"))};
  }
  const number = (value) => (value === "" ? null : Number(value));
  const read = () => Object.fromEntries(all("#main .task-row").map((row) => {
    const eta = row.querySelector(".task-eta");
    return [row.dataset.task, [number(eta.dataset.start), number(eta.dataset.eta), eta.dataset.forecast === "true", text(eta), eta.title]];
  }));
  const toggle = async (mode) => {
    const before = JSON.stringify(read());
    all('#main [aria-label="Estimation"] button').find((button) => button.dataset.estimation === mode).click();
    await until(() => JSON.stringify(read()) !== before, 8000);
    await sleep(300);
    return read();
  };
  const found = {none: read(), modes: modes(), ...fits()};
  found.points = await toggle("points");
  found.back = await toggle("none");
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
TREND_READ = """
  const trendOf = () => {
    const select = document.querySelector('#main select[aria-label="Trend"]');
    const days = document.querySelector('#main input[aria-label="Velocity days"]');
    const note = document.querySelector("#main .burn-forecast");
    const marker = document.querySelector("#main svg.burn .forecast-line");
    return {
      value: select.value, options: all("option", select).map((option) => [option.value, text(option)]), days: [Number(days.value), days.getClientRects().length > 0],
      note: note ? [note.dataset.forecast === "" ? null : Number(note.dataset.forecast), text(note)] : null, marker: marker ? Number(marker.dataset.forecast) : null,
      lines: all("#main svg.burn path.burn-trend").map((path) => [path.dataset.series, Number(path.dataset.from), Number(path.dataset.to)]),
      points: all('#main svg.burn circle.burn-point[data-series="remaining"]').map((circle) => [Number(circle.dataset.t), Number(circle.dataset.value)]),
    };
  };
  const chart = async () => until(() => document.querySelector("#main svg.burn") && document.querySelector('#main select[aria-label="Trend"]'), 8000);
"""
TREND_SET = """(async () => {@HELPERS@@PLAN_HELPERS@@TREND_READ@
  if (!(await chart())) {
    return {error: text(document.getElementById("main"))};
  }
  const before = trendOf();
  const shown = new Set(all("#toasts .toast"));
  await choose(document.querySelector('#main select[aria-label="Trend"]'), "@MODE@");
  const toasts = [await fresh(shown, "Trend: ")];
  if ("@MODE@" === "velocity") {
    const days = document.querySelector('#main input[aria-label="Velocity days"]');
    const again = new Set(all("#toasts .toast"));
    days.value = "@DAYS@";
    days.dispatchEvent(new Event("change", {bubbles: true}));
    toasts.push(await fresh(again, "Trend: velocity over @DAYS@ days"));
  }
  await sleep(400);
  return {before, after: trendOf(), toasts, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS).replace("@TREND_READ@", TREND_READ)
TREND_RELOADED = """(async () => {@HELPERS@@PLAN_HELPERS@@TREND_READ@
  if (!(await chart())) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(300);
  return {...trendOf(), ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS).replace("@TREND_READ@", TREND_READ)
STEP_TIPS = """(async () => {@HELPERS@@PLAN_HELPERS@@TREND_READ@
  if (!(await chart())) {
    return {error: text(document.getElementById("main"))};
  }
  const steps = all('#main svg.burn circle.burn-point[data-series="remaining"]').map((circle) => ({
    t: Number(circle.dataset.t), started: circle.dataset.started, ended: circle.dataset.ended, joined: circle.dataset.joined, tip: text(circle.querySelector("title")),
    series: all(`#main svg.burn circle.burn-point[data-step="${circle.dataset.step}"]`).map((mark) => mark.dataset.series),
  }));
  const shown = new Set(all("#toasts .toast"));
  await choose(document.querySelector('#main select[aria-label="Trend"]'), "off");
  const reset = await fresh(shown, "Trend: off");
  await sleep(300);
  return {steps, reset, note: Boolean(document.querySelector("#main .burn-forecast")), lines: all("#main svg.burn path.burn-trend").length, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS).replace("@TREND_READ@", TREND_READ)
TASKS_3D = """(async () => {@HELPERS@@PLAN_HELPERS@
  const note = () => text(document.querySelector("#main .space-note")) || "";
  const ready = await until(() => window.e2eGraphs && document.querySelector("#main .graph3d canvas") && !note().startsWith("Loading"), 15000);
  if (!ready) {
    return {error: text(document.querySelector("#main .graph"))};
  }
  const graph = () => window.e2eGraphs[window.e2eGraphs.length - 1];
  const id = (end) => (typeof end === "object" ? end.id : end);
  const look = () => {
    const data = graph().graphData();
    const color = graph().linkColor();
    return {
      note: note(), layouts: all('#main [aria-label="Layout"] button').map((button) => [button.dataset.layout, button.getAttribute("aria-pressed")]),
      nodes: data.nodes.map((node) => [node.id, Number.isFinite(node.fz) ? node.fz : null, Number.isFinite(node.ts) ? node.ts : null]),
      links: data.links.map((link) => [id(link.source), id(link.target), link.kind, color(link)]),
      label: (() => {
        const shown = graph().nodeLabel()(data.nodes.find((node) => node.id === "work/t5"));
        return shown instanceof Element ? shown.textContent : String(shown);
      })(),
    };
  };
  const layout = async (mode, word) => {
    all('#main [aria-label="Layout"] button').find((button) => button.dataset.layout === mode).click();
    await until(() => note().endsWith(word), 8000);
    await sleep(400);
    return look();
  };
  const css = getComputedStyle(document.documentElement);
  const palette = Object.fromEntries(["violet", "info", "warn"].map((role) => [role, css.getPropertyValue(`--${role}`).trim()]));
  const force = look();
  const time = await layout("time", "Time");
  const field = document.querySelector('#main input[aria-label="Find a node"]');
  field.value = "work/t5";
  field.dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(200);
  const chip = all("#main .hits .chip").find((node) => node.dataset.hit === "work/t5");
  if (!chip) {
    return {error: "no search hit", force, time};
  }
  chip.click();
  await sleep(600);
  const dialog = document.getElementById("popup");
  const eta = dialog.querySelector(".task-eta");
  const popup = {
    open: dialog.open, title: text(dialog.querySelector(".popup-box .panel-title")), id: text(dialog.querySelector(".popup-head .task-id")), picked: document.querySelector("#main .graph3d").dataset.picked || null,
    eta: eta ? eta.dataset.eta : null, open_button: name(dialog.querySelector(".popup-body .actions button")), line: dialog.querySelector(".leader line").getAttribute("display") !== "none",
  };
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(300);
  popup.closed = [dialog.open, document.querySelector("#main .graph3d").dataset.picked || null];
  const back = await layout("none", "Force");
  await sleep(1200);
  return {palette, force, time, popup, back: back.note, ...fits()};
})()""".replace("@HELPERS@", HELPERS).replace("@PLAN_HELPERS@", PLAN_HELPERS)
PLAN_VALUES = {1920: "13", 1366: "21", 390: "34"}
TREND_DAYS = {1920: 7, 1366: 3, 390: 14}
STATUS_ORDER = ["queued", "awaiting", "claimed", "running", "blocked", "stale", "done", "stopped"]
