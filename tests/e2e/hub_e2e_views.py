from __future__ import annotations

from hub_e2e_kit import FITS, HELPERS, OVERLAP

PROBE = """(async () => {@HELPERS@
  await screenShown(8000);
  await until(() => !(text(document.querySelector("#main .space-note")) || "").startsWith("Loading") && !all("#main .empty h2").some((title) => text(title).endsWith("…")), 8000);
  const badge = (button) => {
    const next = button.nextElementSibling;
    const found = button.querySelector(".badge") || (next && next.matches("a.badge") ? next : null);
    return found && !found.hidden ? text(found) : null;
  };
  const icons = all("svg.bi").filter((svg) => !svg.closest(".sprite"));
  const banner = document.getElementById("mayday");
  return {
    hash: location.hash,
    title: document.title,
    h1: text(document.querySelector("h1")),
    header: all("header.top button[id]").map((button) => button.id),
    tabs: all("#tabs > .tab-group > button").map(name),
    subs: all("#tabs .subtabs button").map(name),
    badges: Object.fromEntries(all("#tabs button").map((button) => [button.id, badge(button)])),
    banner: banner.hidden ? null : text(banner),
    rail: Boolean(document.getElementById("rail")),
    views: all('#main [aria-label="View"] button').map(name),
    layouts: all('#main [aria-label="Layout"] button').map(name),
    chips: all('#main [aria-label="Categories"] button').map(name),
    menus: all("#main details.menu > summary").map(name),
    time: text(document.querySelector("#rates .rate-window")),
    replay: Boolean(document.querySelector("#rates .span-slider input[type=range]")),
    custom: Boolean(document.querySelector('#main details.menu input[type="datetime-local"]')),
    toolbar: all('#main [role="toolbar"] > *').map((node) => name(node.tagName === "DETAILS" ? node.querySelector("summary") : node.querySelector("button") || node)),
    spot: (() => {
      const box = document.getElementById("radio-spot");
      return box ? {hidden: box.hidden, channels: [...box.querySelector("form.composer select").options].map((option) => option.value)} : null;
    })(),
    composers: all("form.composer").map((form) => (form.closest("#radio-spot") ? "spot" : "other")),
    inbox: all("#main .inbox-list > li").length,
    icons: icons.length,
    unlabelled: icons.map((svg) => svg.parentElement.closest(':not([aria-hidden="true"])')).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).map((owner) => owner.outerHTML.slice(0, 160)),
    broken: all("svg.bi use").filter((use) => !document.getElementById(use.getAttribute("href").slice(1))).map((use) => use.getAttribute("href")),
    states: all("#main span.state").map(name),
    deletes: all('#main button[aria-label="Delete"], #main button[aria-label="Delete all merged"]').map((button) => [name(button), button.disabled, button.title]),
    spawn: all("#main .spawn-tree li").map((item) => [item.dataset.kind, item.dataset.running || null]),
    marks: all("#main svg.chart .node").length,
    note: text(document.querySelector("#main .space-note")),
    canvas: Boolean(document.querySelector("#main .graph3d canvas")),
    org: all("#main .org-chart .org-row[data-office]").map((row) => [row.dataset.office, text(row.querySelector(".org-holder"))]),
    toggles: all("#main .org-toggle").map((button) => [name(button), button.getAttribute("aria-expanded")]),
    order: all("#main .agent-order li").map((item) => item.dataset.name),
    taskFilters: all('#main [aria-label="Task filters"] button').map((button) => [button.dataset.filter, button.getAttribute("aria-pressed"), text(button.querySelector(".count"))]),
    taskRows: all("#main .task-row").map((row) => [row.dataset.task, row.classList.contains("open-work")]),
    columns: all("#main .task-column").map((column) => [column.dataset.column, all(`#main .kanban-cell[data-column="${column.dataset.column}"] .task-card`).map((card) => card.dataset.task)]),
    matrix: [all("#main table.matrix thead th").length, all("#main table.matrix tbody tr").length, all("#main table.matrix td .letter").map(text).join("")],
    flows: all("#main .flow").map((flow) => flow.dataset.flow),
    flowEdges: all("#main svg.chart path.flow").map((path) => path.dataset.side),
    openWork: all("#main .open-work").length,
    panel: all("#drawer, .drawer, #main aside, #main .panel, #main .graph-body").length,
    nodeChips: all("#main .space-list, #main .chip[data-node]").length,
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
    tall: document.documentElement.scrollHeight > window.innerHeight,
  };
})()""".replace("@HELPERS@", HELPERS)
INBOX_CHIP = """(async () => {@HELPERS@
  const chip = (id) => document.querySelector(`#main [aria-label="Task filters"] button[data-filter="${id}"]`);
  chip("operator").click();
  await until(() => location.hash === "#tasks/operator" && document.querySelector("#main .inbox-list"), 4000);
  const inbox = {hash: location.hash, items: all("#main .inbox-list > li").length, counted: Number(text(chip("operator").querySelector(".count"))), pressed: chip("operator").getAttribute("aria-pressed"), current: all("#tabs button[aria-current=page]").map(name)};
  chip("grant").click();
  await until(() => location.hash.startsWith("#tasks/"), 4000);
  await sleep(300);
  return {inbox, back: {hash: location.hash, rows: all("#main .task-row").map((row) => [row.dataset.task, text(row.querySelector(".pill"))])}};
})()""".replace("@HELPERS@", HELPERS)
ACTIONS = """(async () => {@HELPERS@
  const press = async (key) => {
    document.dispatchEvent(new KeyboardEvent("keydown", {key, bubbles: true}));
    await sleep(300);
    return location.hash;
  };
  const found = {keys: [await press("3"), await press("4"), await press("5"), await press("1"), await press("2")]};
  document.getElementById("settings-open").click();
  await sleep(300);
  found.ambience = all(".sheet-box form > section:first-child button").map((button) => button.id);
  found.sections = all(".sheet-box form.settings > section > h3").map(text);
  found.radioFields = all('.sheet-box [aria-label="Squelch"], .sheet-box [aria-label="Classes"], .sheet-box [aria-label="Speakers"], .sheet-box [aria-label="Mode"], .sheet-box .sound-row, .sheet-box .stream-row').length;
  found.settingsUnlabelled = all(".sheet-box svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length;
  document.querySelector(".sheet-head button").click();
  document.getElementById("palette-open").click();
  await sleep(300);
  found.palette = all(".palette-list li > span:first-child").map(text);
  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(200);
  document.querySelector('#main [aria-label="Categories"] button:nth-child(2)').click();
  await sleep(900);
  document.querySelector('#main button.linkish[title^="Open "]').click();
  await sleep(500);
  found.popup = all("#popup input[type=radio]").map((input) => [input.value, input.checked]);
  found.popupUnlabelled = all("#popup svg.bi").map((svg) => svg.parentElement).filter((owner) => !text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label"))).length;
  found.leader = [document.getElementById("popup").open, document.querySelector("#popup .leader line").getAttribute("display")];
  return found;
})()""".replace("@HELPERS@", HELPERS)
POPUPS = """
  const dialog = document.getElementById("popup");
  const box = dialog.querySelector(".popup-box");
  const line = dialog.querySelector(".leader line");
  const click = (target) => target.dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true}));
  const tint = document.createElement("i");
  tint.style.color = "var(--alarm)";
  document.body.append(tint);
  const red = getComputedStyle(tint).color;
  tint.remove();
  const tall = () => document.documentElement.scrollHeight > innerHeight;
  const look = (node) => ({picked: node.classList.contains("picked"), size: Math.round(node.querySelector("circle").getBoundingClientRect().width), red: getComputedStyle(node.querySelector("circle")).fill === red});
  const opened = () => {
    const rect = box.getBoundingClientRect();
    const ends = line.getAttribute("display") === "none" ? null : ["x1", "y1", "x2", "y2"].map((key) => Number(line.getAttribute(key)));
    return {
      open: dialog.open, fade: [dialog.classList.contains("fade"), getComputedStyle(dialog).animationName], title: text(box.querySelector(".panel-title")), opacity: Number(getComputedStyle(box).opacity), line: ends,
      onBox: Boolean(ends) && (Math.abs(ends[2] - rect.left) < 1 || Math.abs(ends[2] - rect.right) < 1 || Math.abs(ends[3] - rect.top) < 1 || Math.abs(ends[3] - rect.bottom) < 1),
      inside: rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight,
      tall: tall(), wide: document.documentElement.scrollWidth > innerWidth + 1, panel: all("#drawer, .drawer, #main aside, #main .panel, #main .graph-body").length,
    };
  };
  const away = async (pick) => {
    const rect = box.getBoundingClientRect();
    const [, x, y] = [[rect.left, rect.left / 2, innerHeight / 2], [innerWidth - rect.right, (rect.right + innerWidth) / 2, innerHeight / 2], [rect.top, innerWidth / 2, rect.top / 2], [innerHeight - rect.bottom, innerWidth / 2, (rect.bottom + innerHeight) / 2]].sort((a, b) => b[0] - a[0])[0];
    const outside = (await until(() => document.elementFromPoint(x, y) === dialog && dialog, 3000)) || document.elementFromPoint(x, y);
    click(outside);
    await sleep(250);
    return {...look(pick()), open: dialog.open, outside: outside === dialog};
  };
"""
POPUP_ORBIT = """(async () => {@HELPERS@@POPUPS@
  const pick = () => document.querySelector('#main svg .node[data-pick="s2"]');
  if (!(await until(pick, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const before = look(pick());
  const flat = !tall();
  click(pick());
  await sleep(400);
  const art = box.querySelector(".popup-head .avatar.big");
  const face = art ? {key: art.dataset.face, svg: Boolean(art.querySelector("svg.face-art .mouth")), text: art.textContent} : null;
  const shown = {...opened(), ...look(pick()), sections: all("h3", box).map((head) => head.firstChild.textContent), composer: Boolean(box.querySelector("form textarea")), offices: text(box.querySelector(".popup-body > div:not(.agent-settings) > p")), face};
  const gone = await away(pick);
  click(pick());
  await sleep(300);
  const again = dialog.open;
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(250);
  const escaped = {...look(pick()), open: dialog.open, again};
  click(pick());
  await sleep(500);
  return {before, flat, shown, gone, escaped, last: dialog.open};
})()""".replace("@HELPERS@", HELPERS).replace("@POPUPS@", POPUPS)
POPUP_ARTIFACT = """(async () => {@HELPERS@@POPUPS@
  const first = await until(() => document.querySelector('#main svg .node[data-pick^="branch:"]'), 8000);
  if (!first) {
    return {error: text(document.getElementById("main"))};
  }
  const id = first.dataset.pick;
  const pick = () => all("#main svg .node[data-pick]").find((node) => node.dataset.pick === id);
  const before = look(pick());
  const flat = !tall();
  click(pick());
  await sleep(400);
  const shown = {...opened(), ...look(pick()), label: first.getAttribute("aria-label").split(",")[0]};
  const gone = await away(pick);
  click(pick());
  await sleep(400);
  return {before, flat, shown, gone, last: dialog.open};
})()""".replace("@HELPERS@", HELPERS).replace("@POPUPS@", POPUPS)
PICK_3D = """(async () => {@HELPERS@
  const field = await until(() => document.querySelector('#main input[aria-label="Find a node"]'), 8000);
  const ready = await until(() => document.querySelector("#main .graph3d canvas") && !text(document.querySelector("#main .space-note")).startsWith("Loading"), 8000);
  if (!field || !ready) {
    return {error: text(document.querySelector("#main .graph"))};
  }
  const type = async (value) => {
    field.value = value;
    field.dispatchEvent(new Event("input", {bubbles: true}));
    await sleep(150);
    return all("#main .hits .chip").map((chip) => [chip.dataset.hit, text(chip)]);
  };
  const tree = await (await fetch("/api/tree", {cache: "no-store"})).json();
  const found = {empty: await type(""), twins: tree.repos.flatMap((repo) => repo.branches).filter((branch) => branch.name === "main").length, twin: await type("main"), hits: await type("@QUERY@")};
  found.flat = document.documentElement.scrollHeight <= innerHeight;
  const chip = all("#main .hits .chip").find((node) => node.dataset.hit.startsWith("@PREFIX@"));
  if (!chip) {
    return {error: found};
  }
  chip.click();
  await sleep(600);
  const dialog = document.getElementById("popup");
  const line = dialog.querySelector(".leader line");
  const host = () => document.querySelector("#main .graph3d");
  found.opened = {
    open: dialog.open, title: text(dialog.querySelector(".popup-box .panel-title")), label: text(chip), hit: chip.dataset.hit, picked: host().dataset.picked || null,
    line: line.getAttribute("display") !== "none", lists: all("#main .space-list, #main .chip[data-node]").length, flat: document.documentElement.scrollHeight <= innerHeight,
  };
  dialog.dispatchEvent(new MouseEvent("click", {bubbles: true}));
  await sleep(300);
  found.closed = {open: dialog.open, picked: host().dataset.picked || null};
  chip.click();
  await sleep(600);
  return found;
})()""".replace("@HELPERS@", HELPERS)
RULES_OVERLAP = """(async () => {@HELPERS@@CLASHES@
  const open = document.querySelector(".sheet-head button");
  if (open) {
    open.click();
  }
  (await until(() => document.getElementById("controls-tab-rules"), 8000)).click();
  (await until(() => document.querySelector("#main [data-new-rule]"), 8000)).click();
  const rules = await until(() => document.querySelector("#sheet .rule-form"), 8000);
  const kind = rules.querySelector("select");
  const found = {};
  for (const value of ["decision", "review", "ask"]) {
    kind.value = value;
    kind.dispatchEvent(new Event("change", {bubbles: true}));
    await sleep(150);
    found[value] = {...clashes(rules), labels: all("label", rules).filter(shown).map(words)};
  }
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@CLASHES@", OVERLAP)
SETTINGS_OVERLAP = """(async () => {@HELPERS@@CLASHES@
  document.getElementById("settings-open").click();
  const settings = await until(() => document.querySelector(".sheet-box form.settings"), 8000);
  const theme = all("select", settings).find((select) => [...select.options].some((option) => option.value === "custom"));
  theme.value = "custom";
  theme.dispatchEvent(new Event("change", {bubbles: true}));
  await sleep(250);
  const place = all("section", settings).find((section) => text(section.querySelector("h3")) === "Location");
  place.scrollIntoView({block: "start"});
  return clashes(settings);
})()""".replace("@HELPERS@", HELPERS).replace("@CLASHES@", OVERLAP)
PRESENCE_HELPERS = """
  const states = () => all("#main .presence:not(label)").map((node) => node.dataset.state).sort();
  const statusMenu = () => {
    const menu = all('#main [role="toolbar"] details.menu').find((node) => name(node.querySelector("summary")) === "Status");
    menu.open = true;
    return menu;
  };
  const looks = (menu) => all("input[data-look]", menu).map((input) => [input.dataset.look, input.checked]);
  const graph3d = async (faces) => {
    const box = await until(() => {
      const found = document.querySelector("#main .graph3d");
      return found && found.dataset.faces !== undefined && (faces === null || found.dataset.faces === faces) ? found : null;
    }, 15000);
    return box ? [Number(box.dataset.faces), Number(box.dataset.badges)] : null;
  };
"""
PRESENCE_WALK = """(async () => {@HELPERS@@PRESENCE@
  const views = {};
  for (const view of ["orbit", "chord", "swimlane", "tree", "hierarchy"]) {
    location.hash = `#agents/${view}`;
    await screenShown(6000);
    await until(() => all("#main .presence:not(label)").length, 6000);
    views[view] = states();
  }
  location.hash = "#agents/orbit";
  await screenShown(6000);
  const node = await until(() => document.querySelector('#main svg .node[data-pick="s1"]'), 6000);
  const motion = getComputedStyle(node.querySelector(".presence .glyph")).animationName;
  node.dispatchEvent(new MouseEvent("click", {bubbles: true}));
  const mark = await until(() => document.querySelector("#popup .presence"), 4000);
  const profile = mark ? [mark.dataset.state, text(mark), mark.getAttribute("aria-label")] : null;
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(300);
  location.hash = "#agents/3d";
  const shown = await graph3d(null);
  const menu = statusMenu();
  const before = looks(menu);
  menu.querySelector('input[data-look="working"]').click();
  menu.querySelector('input[data-look="faces"]').click();
  const hidden = await graph3d("0");
  location.hash = "#agents/orbit";
  await screenShown(6000);
  await until(() => document.querySelector('#main svg .node[data-pick="s2"]'), 6000);
  return {views, motion, profile, shown, before, hidden, orbit: states(), @FITS@};
})()""".replace("@HELPERS@", HELPERS).replace("@PRESENCE@", PRESENCE_HELPERS).replace("@FITS@", FITS)
PRESENCE_READ = """(async () => {@HELPERS@@PRESENCE@
  await until(() => document.querySelector('#main svg .node[data-pick="s2"]'), 8000);
  await sleep(300);
  const menu = statusMenu();
  const kept = {boxes: looks(menu), orbit: states()};
  menu.querySelector('input[data-look="working"]').click();
  menu.querySelector('input[data-look="faces"]').click();
  await sleep(300);
  const back = states();
  location.hash = "#agents/3d";
  return {...kept, back, restored: await graph3d(null)};
})()""".replace("@HELPERS@", HELPERS).replace("@PRESENCE@", PRESENCE_HELPERS)
CAMERA = """(async () => {@HELPERS@
  const ready = await until(() => window.e2eGraphs && document.querySelector("#main .graph3d canvas") && !text(document.querySelector("#main .space-note")).startsWith("Loading"), 15000);
  if (!ready) {
    return {error: text(document.querySelector("#main .graph"))};
  }
  const graph = window.e2eGraphs[window.e2eGraphs.length - 1];
  const position = () => {
    const at = graph.cameraPosition();
    return [at.x, at.y, at.z];
  };
  await sleep(5500);
  let [fed, stops] = [0, 0];
  const stopped = graph.onEngineStop();
  graph.onEngineStop(() => {
    stops += 1;
    stopped();
  });
  const feed = graph.graphData;
  graph.graphData = function (...args) {
    fed += args.length;
    return feed.apply(graph, args);
  };
  const built = position();
  const canvas = document.querySelector("#main .graph3d canvas");
  const rect = canvas.getBoundingClientRect();
  for (let turn = 0; turn < 4; turn += 1) {
    canvas.dispatchEvent(new WheelEvent("wheel", {deltaY: -120, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2, bubbles: true, cancelable: true}));
    await sleep(60);
  }
  await sleep(900);
  const moved = position();
  const refreshes = [];
  for (let round = 0; round < 2; round += 1) {
    const [feeds, ends] = [fed, stops];
    document.dispatchEvent(new Event("visibilitychange"));
    const rebuilt = Boolean(await until(() => fed > feeds, 8000));
    const settled = Boolean(await until(() => stops > ends, 10000));
    await sleep(900);
    refreshes.push({rebuilt, settled, camera: position()});
  }
  all("#main button").find((button) => name(button) === "Reset view").click();
  await sleep(1500);
  return {hooked: typeof stopped === "function", built, moved, refreshes, reset: position()};
})()""".replace("@HELPERS@", HELPERS)
