from __future__ import annotations

POP = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => @PINS@);
  location.hash = "@VIEW@";
  await screenShown(8000);
  if (@SPOT@) {
    await openSpot();
  } else {
    await closeSpot();
  }
  await settle();
  await sleep(500);
  const outside = (layer) => {
    const edge = box(layer);
    const clips = [["viewport", {top: 0, bottom: innerHeight, left: 0, right: innerWidth}]];
    for (let node = layer.parentElement; node && node !== document.documentElement; node = node.parentElement) {
      const look = getComputedStyle(node);
      if (look.overflowX !== "visible" || look.overflowY !== "visible") {
        clips.push([`${node.tagName}.${node.getAttribute("class")}`, box(node)]);
      }
    }
    return clips.filter(([, clip]) => edge.top < clip.top - 1 || edge.bottom > clip.bottom + 1 || edge.left < clip.left - 1 || edge.right > clip.right + 1)
      .map(([name, clip]) => `${name} [${Math.round(clip.top)},${Math.round(clip.bottom)}] vs [${Math.round(edge.top)},${Math.round(edge.bottom)}]`);
  };
  const out = [];
  for (const selector of @ROOTS@) {
    const root = document.querySelector(selector);
    if (!root || !(await until(() => root.querySelectorAll(".station").length === 3, 8000))) {
      out.push({selector, error: "no stations"});
      continue;
    }
    const fold = root.querySelector("details.radio-station");
    const summary = fold.querySelector("summary");
    const layer = fold.querySelector(".station-body");
    fold.scrollIntoView({block: "center"});
    await sleep(200);
    summary.focus();
    summary.click();
    await sleep(300);
    const whole = all(".station", layer).filter((row) => box(row).top >= box(layer).top - 1 && box(row).bottom <= box(layer).bottom + 1).length;
    const opened = {open: fold.open, side: fold.dataset.side, height: Math.round(box(layer).height), outside: outside(layer), whole};
    layer.querySelector(".station button").focus();
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
    await sleep(200);
    const escape = [fold.open, document.activeElement === summary];
    summary.click();
    await sleep(300);
    const again = {open: fold.open, outside: outside(layer)};
    press(document.getElementById("main"));
    await sleep(200);
    out.push({selector, opened, escape, again, click: [fold.open, document.activeElement === summary, document.activeElement === document.body]});
  }
  return out;
})()"""
FOCUS = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const spot = await openSpot();
  await until(() => spot.querySelectorAll(".station").length === 3 && spot.querySelector(".radio-row"), 8000);
  await settle();
  await sleep(300);
  const fold = spot.querySelector("details.radio-station");
  const night = await until(() => all("details.menu").find((menu) => menu.querySelector("summary").getAttribute("aria-label") === "Day/Night"), 8000);
  const label = (node) => (node ? `${node.tagName}.${node.getAttribute("class")}[${node.getAttribute("aria-label") || text(node).slice(0, 24)}]` : "null");
  const tab = () => spot.querySelector('.radio-tabs [role="tab"]:not([aria-selected="true"])');
  const cases = {};
  const run = async (key, menu, target) => {
    press(menu.querySelector("summary"));
    await sleep(250);
    const opened = menu.open;
    const node = target();
    press(node);
    await sleep(400);
    const active = document.activeElement;
    cases[key] = {opened, closed: !menu.open, active: label(active), summary: Boolean(active && active.matches("summary")), history: Boolean(active && active.closest(".radio-logbox")), body: active === document.body};
    menu.open = false;
    await sleep(150);
  };
  await run("night-tab", night, tab);
  await run("fold-tab", fold, tab);
  await run("night-main", night, () => document.getElementById("main"));
  await run("fold-main", fold, () => document.getElementById("main"));
  press(fold.querySelector("summary"));
  await sleep(250);
  fold.querySelector(".station button").focus();
  document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(200);
  cases.escape = {closed: !fold.open, toggle: document.activeElement === fold.querySelector("summary")};
  return cases;
})()"""
ROWS = """(async () => {@HELPERS@@PROBES@@LOADS@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const spot = await openSpot();
  await until(() => spot.querySelectorAll(".radio-row").length > 2, 8000);
  await settle();
  await sleep(300);
  const rows = () => spot.querySelectorAll(".radio-row").length;
  const deliver = async () => {
    const before = rows();
    await fetch("/api/voice/@LIVE@", {cache: "no-store"});
    window.dispatchEvent(new Event("focus"));
    const done = await until(() => rows() > before, 20000);
    await sleep(300);
    return Boolean(done);
  };
  const row = spot.querySelectorAll(".radio-row")[1];
  const button = row.querySelector(".radio-pick");
  const held = () => {
    const active = document.activeElement;
    const owner = active ? active.closest(".radio-row") : null;
    return {same: active === button, key: owner ? owner.dataset.key : null, pick: Boolean(active && active.matches(".radio-pick")), body: active === document.body};
  };
  button.focus();
  const start = {...held(), want: row.dataset.key};
  const fresh = {...held(), delivered: await deliver()};
  const real = Date.now;
  Date.now = () => real.call(Date) + 60000;
  window.dispatchEvent(new Event("focus"));
  const tick = {...held(), ticked: await loaded(1, 20000)};
  Date.now = real;
  const tab = spot.querySelector('.radio-tabs [role="tab"][aria-selected="true"]');
  tab.focus();
  let focusins = 0;
  document.addEventListener("focusin", () => {
    focusins += 1;
  }, true);
  const delivered = [await deliver(), await deliver(), await deliver()];
  return {start, fresh, tick, tabs: {delivered, focusins, same: document.activeElement === tab, tab: document.activeElement.getAttribute("data-tab")}};
})()"""
KEYS = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const spot = await openSpot();
  spot.querySelector('.radio-tabs [role="tab"][data-tab="all"]').click();
  const dups = () => all(".radio-row", spot).filter((node) => text(node.querySelector(".radio-line")).startsWith("dup "));
  await until(() => dups().length === 2, 8000);
  await settle();
  await sleep(300);
  const rows = () => spot.querySelectorAll(".radio-row").length;
  const deliver = async () => {
    const before = rows();
    await fetch("/api/voice/@LIVE@", {cache: "no-store"});
    window.dispatchEvent(new Event("focus"));
    const done = await until(() => rows() > before, 20000);
    await sleep(300);
    return Boolean(done);
  };
  const line = (node) => (node && node.closest(".radio-row") ? text(node.closest(".radio-row").querySelector(".radio-line")) : null);
  const out = {keys: dups().map((node) => node.dataset.key)};
  for (const word of @DUPS@) {
    const button = dups().find((node) => text(node.querySelector(".radio-line")) === word).querySelector(".radio-pick");
    button.focus();
    const delivered = await deliver();
    const active = document.activeElement;
    const result = {delivered, same: active === button, line: line(active), popup: null};
    if (active && active.matches(".radio-pick")) {
      active.click();
      result.popup = await until(() => (popup().open && popup().querySelector(".radio-full") ? popup().querySelector(".radio-full").textContent : null), 4000);
      (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
      await until(() => !popup().open, 2000);
    }
    out[word] = result;
  }
  const victim = all(".radio-row", spot).find((node) => node.dataset.class === "newsletter");
  victim.querySelector(".radio-pick").focus();
  const chip = spot.querySelector('.chip-select[data-chip="class"] select');
  chip.value = "call";
  chip.dispatchEvent(new Event("change", {bubbles: true}));
  await sleep(500);
  const near = document.activeElement;
  out.filtered = {gone: !victim.isConnected, pick: Boolean(near && near.matches(".radio-pick")), class: near && near.closest(".radio-row") ? near.closest(".radio-row").dataset.class : null};
  const search = spot.querySelector('.radio-logbox input[type="search"]');
  search.value = "no radio row says this";
  search.dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(500);
  out.emptied = {gone: !spot.querySelector(".radio-row"), list: document.activeElement === spot.querySelector("ul.radio-log")};
  search.value = "";
  search.dispatchEvent(new Event("input", {bubbles: true}));
  chip.value = "";
  chip.dispatchEvent(new Event("change", {bubbles: true}));
  await sleep(300);
  return out;
})()"""
BANNER = """(async () => {@HELPERS@@PROBES@@LOADS@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const banner = document.getElementById("mayday");
  await until(() => !banner.hidden && banner.querySelector("button"), 8000);
  await settle();
  await sleep(300);
  const records = [];
  new MutationObserver((list) => records.push(...list)).observe(banner, {childList: true, subtree: true, characterData: true, attributes: true});
  const cancel = banner.querySelector("button");
  cancel.focus();
  const polled = await loaded(2, 30000);
  const steady = {polled, mutations: records.length, focus: document.activeElement === cancel, body: document.activeElement === document.body};
  records.length = 0;
  await fetch("/api/voice/@SILENCE@", {cache: "no-store"});
  const again = await loaded(3, 45000);
  const added = records.filter((record) => record.type === "childList" && record.addedNodes.length > 0).length;
  return {steady, changed: {polled: again, text: text(banner.querySelector(".text")), added, shown: !banner.hidden, cancel: Boolean(banner.querySelector("button"))}};
})()"""
COMPOSE_HOME = """(async () => {@HELPERS@@PROBES@
  const bodies = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path) === "/api/messages") {
      bodies.push(JSON.parse(init.body));
    }
    return send(path, init);
  };
  window.confirm = () => true;
  const spot = await openSpot();
  const spotText = spot.querySelector("form.composer textarea");
  spotText.value = "draft kept in the spot";
  spotText.dispatchEvent(new Event("input", {bubbles: true}));
  await ViewStore.update("home.pins", () => [{kind: "panel", id: "radio", w: 12, h: 7}, {kind: "panel", id: "radio-speak", w: 6, h: 5}, {kind: "panel", id: "radio-log", w: 6, h: 5}]);
  location.hash = "#home";
  await screenShown(8000);
  await until(() => tile("radio-speak") && tile("radio-log") && tile("radio") && tile("radio-log").querySelector(".radio-row"), 10000);
  await sleep(400);
  const homeSpeak = tile("radio-speak");
  const form = (root) => root.querySelector("form.composer");
  const area = (root) => form(root).querySelector("textarea");
  const record = (root) => all("button", form(root)).find((button) => button.hasAttribute("aria-pressed"));
  const note = (root) => {
    const audio = form(root).querySelector(".voice-note audio");
    return audio ? audio.getAttribute("src").replace("/api/voice/", "").replace(".wav", "") : null;
  };
  const drafts = [area(spot).value, area(homeSpeak).value, area(tile("radio")).value];
  record(spot).click();
  await sleep(1200);
  const first = record(spot).getAttribute("aria-pressed");
  record(homeSpeak).click();
  const handed = await until(() => (record(homeSpeak).getAttribute("aria-pressed") === "true" ? [record(spot).getAttribute("aria-pressed"), "true"] : null), 5000);
  const spotHeard = await until(() => (note(spot) && area(spot).value.includes("hello from the mic") ? area(spot).value : null), 30000);
  const homeBefore = area(homeSpeak).value;
  await sleep(800);
  record(homeSpeak).click();
  const homeHeard = await until(() => (note(homeSpeak) && area(homeSpeak).value.includes("hello from the mic") ? area(homeSpeak).value : null), 30000);
  const notes = [note(spot), note(homeSpeak)];
  const sendFrom = async (root, to, words, attach) => {
    const [channel, recipient] = all("select", form(root));
    channel.value = "post";
    channel.dispatchEvent(new Event("change", {bubbles: true}));
    await until(() => [...recipient.options].some((option) => option.value === to), 8000);
    recipient.value = to;
    area(root).value = words;
    area(root).dispatchEvent(new Event("input", {bubbles: true}));
    const box = form(root).querySelector('.voice-note input[type="checkbox"]');
    if (box) {
      box.checked = attach;
    }
    const shownBefore = new Set(all("#toasts .toast"));
    form(root).querySelector('button[type="submit"]').click();
    return until(() => all("#toasts .toast").filter((node) => !shownBefore.has(node)).map(text).find((entry) => entry.startsWith("Post to")), 20000);
  };
  const spotSent = await sendFrom(spot, "Stage", "plain text from the spot", false);
  const homeAttach = Boolean(form(homeSpeak).querySelector('.voice-note input[type="checkbox"]'));
  const homeSent = await sendFrom(homeSpeak, "Docs", "voice from the Home tile", true);
  await closeSpot();
  document.getElementById("toasts").replaceChildren();
  return {drafts, first, handed, spotHeard, homeBefore, homeHeard, notes, spotSent, homeAttach, homeSent, bodies: bodies.map((body) => [body.to, body.text, body.voice])};
})()"""
REPLY_HOME = """(async () => {@HELPERS@@PROBES@
  const spotOpen = () => document.getElementById("radio-open").getAttribute("aria-expanded");
  const reply = async (root) => {
    const row = longRow(root);
    row.scrollIntoView({block: "center"});
    await sleep(200);
    await openRow(row);
    all(".radio-actions button", popup()).find((button) => text(button) === "Reply").click();
    await sleep(300);
  };
  await reply(tile("radio-log"));
  const fromLog = {spot: spotOpen(), popup: popup().open, speak: pick(tile("radio-speak")), whole: pick(tile("radio"))};
  await reply(tile("radio"));
  const fromWhole = {spot: spotOpen(), whole: pick(tile("radio"))};
  const sendFrom = async (root, words) => {
    const area = root.querySelector("form.composer textarea");
    area.value = words;
    area.dispatchEvent(new Event("input", {bubbles: true}));
    const shownBefore = new Set(all("#toasts .toast"));
    root.querySelector('form.composer button[type="submit"]').click();
    return until(() => all("#toasts .toast").filter((node) => !shownBefore.has(node)).map(text).find((entry) => entry.startsWith("Post to")), 20000);
  };
  const sent = await sendFrom(tile("radio"), "reply from the Home radio");
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  const clear = all(".spot-head button", tile("radio")).find((button) => button.getAttribute("aria-label") === "Cancel mayday");
  const enabled = clear ? !clear.disabled : null;
  const shownBefore = new Set(all("#toasts .toast"));
  if (clear) {
    clear.click();
  }
  const lifted = await until(() => all("#toasts .toast").filter((node) => !shownBefore.has(node)).map(text).find((entry) => entry.startsWith("Cancel mayday")), 15000);
  document.getElementById("toasts").replaceChildren();
  return {fromLog, fromWhole, sent, enabled, questions, lifted, spot: spotOpen()};
})()"""
