from __future__ import annotations

LAYOUT = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => []);
  const spot = await openSpot();
  spot.querySelector('.radio-tabs [data-tab="all"]').click();
  await until(() => all(".radio-row .reader", spot).length > 20 && longRow(spot), 20000);
  await sleep(300);
  window.scrollTo(0, 0);
  const cardOf = (node) => (node.parentElement && node.parentElement.closest(".radio-card")) || spot;
  const wider = all("*", spot).filter((node) => node.tagName !== "OPTION" && shown(node) && box(node).width > 0).filter((node) => {
    const own = box(node);
    const card = box(cardOf(node));
    return own.left < card.left - 1 || own.right > card.right + 1;
  }).map((node) => `${node.tagName}.${node.getAttribute("class")}`);
  const list = spot.querySelector(".radio-log");
  const listLook = getComputedStyle(list);
  const rows = all(".radio-row", spot);
  const lineHeight = parseFloat(getComputedStyle(rows[0].querySelector(".radio-line")).lineHeight);
  const lines = rows.map((row) => {
    const line = row.querySelector(".radio-line");
    const look = getComputedStyle(line);
    return {height: Math.round(box(row).height), nowrap: look.whiteSpace === "nowrap", ellipsis: look.textOverflow === "ellipsis", flat: line.scrollHeight <= line.clientHeight + 1 && row.scrollHeight <= row.clientHeight + 1, fits: row.scrollWidth <= row.clientWidth + 1 && box(row).right <= box(list).right + 1, width: line.clientWidth};
  });
  const long = longRow(spot).querySelector(".radio-line");
  const avatars = rows.filter((row) => row.querySelector(".reader")).map((row) => {
    const edge = box(row);
    const line = box(row.querySelector(".radio-line"));
    const faces = all(".reader .avatar", row).filter(shown).map(box);
    return {
      total: Number((row.querySelector(".readers").getAttribute("aria-label").match(/\\d+/) || ["0"])[0]),
      count: faces.length,
      more: all(".readers-more", row).filter(shown).map(text),
      inside: faces.every((face) => face.left >= edge.left - 1 && face.right <= edge.right + 1 && face.top >= edge.top - 1 && face.bottom <= edge.bottom + 1),
      after: faces.every((face) => face.left >= line.right - 1),
      stacked: faces.slice(1).every((face, index) => face.left < faces[index].right),
      sliver: faces.length ? Math.min(...faces.map((face, index) => (index + 1 < faces.length ? faces[index + 1].left : face.right) - face.left)) : null,
    };
  });
  const [device, speak, history] = ["radio-device", "radio-speak", "radio-log"].map((id) => box(spot.querySelector(`[data-panel="${id}"]`)));
  const owners = [spot, ...all("[data-panel]", spot)];
  const controls = all('button, input, select, textarea, summary, [role="tab"]', spot).filter((node) => shown(node) && !node.classList.contains("star"));
  const overlap = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  const covered = owners.map(ownStar).filter(Boolean).flatMap((star) => controls.filter((node) => !node.contains(star) && overlap(box(star), box(node)) > 1).map((node) => `${star.title} over ${node.getAttribute("aria-label") || text(node)}`));
  const knobs = all(".radio-knobs .knob-row", spot).map((row) => Math.round(box(row.querySelector(".knob-label")).left));
  return {
    page: [document.documentElement.scrollWidth, innerWidth], tall: [document.documentElement.scrollHeight, innerHeight, Math.round(box(spot).height)],
    wider, scrollers: scrollersIn(spot),
    list: {overflowY: listLook.overflowY, scrollbar: [listLook.scrollbarWidth, listLook.scrollbarColor], scrolls: list.scrollHeight > list.clientHeight + 1},
    main: getComputedStyle(document.getElementById("main")).scrollbarColor,
    heights: [...new Set(lines.map((line) => line.height))], lineHeight, rows: rows.length,
    single: lines.every((line) => line.nowrap && line.ellipsis && line.flat && line.fits),
    narrowest: Math.min(...lines.map((line) => line.width)),
    long: [long.scrollWidth > long.clientWidth, getComputedStyle(long).textOverflow],
    avatars: {rows: avatars.length, most: Math.max(...avatars.map((row) => row.count)), inside: avatars.every((row) => row.inside), after: avatars.every((row) => row.after), stacked: avatars.filter((row) => row.count > 1).every((row) => row.stacked)},
    folds: avatars.map((row) => [row.total, row.count, row.more]),
    sliver: Math.min(...avatars.map((row) => row.sliver)),
    order: {stacked: device.bottom <= speak.top + 1 && speak.bottom <= history.top + 1 && Math.abs(device.left - speak.left) < 2, beside: device.right <= speak.left && speak.bottom <= history.top + 1 && Math.abs(speak.left - history.left) < 2},
    labels: [...new Set(knobs)].length,
    stars: owners.map((owner) => [owner.dataset.panel, Boolean(ownStar(owner))]), covered,
    stations: [Boolean(spot.querySelector("details.radio-station")), spot.querySelector("details.radio-station").open],
  };
})()"""
POPUP = """(async () => {@HELPERS@@PROBES@
  const spot = document.getElementById("radio-spot");
  const copied = [];
  navigator.clipboard.writeText = (value) => {
    copied.push(value);
    return Promise.resolve();
  };
  const row = longRow(spot);
  row.scrollIntoView({block: "center"});
  await sleep(200);
  const dialog = await openRow(row);
  if (!dialog) {
    return {error: "no popup"};
  }
  const card = dialog.querySelector(".popup-box");
  const fields = Object.fromEntries(all("dl.meta > div", card).map((pair) => [text(pair.querySelector("dt")), text(pair.querySelector("dd"))]));
  const readers = all(".popup-reader", card).map((item) => ({session: item.dataset.session, name: text(item.querySelector("strong")), time: text(item.querySelector(".muted")), acked: item.dataset.acked}));
  const copy = card.querySelector(".radio-copy");
  const said = card.querySelector(".radio-said");
  const heard = () => [copy.getAttribute("aria-label"), said ? text(said) : null];
  const region = said ? [said.getAttribute("role"), said.getAttribute("aria-live"), card.contains(said), shown(said) && box(said).width <= 1] : null;
  copy.click();
  const done = await until(() => (copy.dataset.copied === "true" ? text(copy) : null), 3000);
  const success = heard();
  const buttons = all(".radio-actions button", card).map(text);
  await until(() => copy.getAttribute("aria-label") === "Copy" && copy.dataset.copied === "", 4000);
  const reset = heard();
  navigator.clipboard.writeText = () => Promise.reject(new DOMException("Denied", "NotAllowedError"));
  copy.click();
  await until(() => copy.dataset.copied === "false", 3000);
  const failure = heard();
  return {
    open: dialog.open, title: text(card.querySelector(".popup-head h2")), fields, full: dialog.querySelector(".radio-full").textContent, readers,
    heading: text(card.querySelector("h3")), buttons, copied, shown: done, region, success, reset, failure,
    stray: [...card.childNodes].filter((node) => node.nodeType === 3).map((node) => node.textContent),
    inView: (() => {
      const edge = box(card);
      return edge.left >= 0 && edge.top >= 0 && edge.right <= innerWidth + 1 && edge.bottom <= innerHeight + 1;
    })(),
  };
})()"""
CLOSE_REPLY = """(async () => {@HELPERS@@PROBES@
  const spot = document.getElementById("radio-spot");
  (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(200);
  const escaped = !popup().open;
  const dialog = await openRow(longRow(spot));
  const card = box(dialog.querySelector(".popup-box"));
  const x = card.left > 8 ? Math.floor(card.left / 2) : Math.ceil((card.right + document.documentElement.clientWidth) / 2);
  const hit = document.elementFromPoint(x, Math.round(innerHeight / 2));
  hit.click();
  await sleep(200);
  const outside = [hit === popup(), !popup().open];
  await openRow(longRow(spot));
  all(".radio-actions button", popup()).find((button) => text(button) === "Reply").click();
  await sleep(300);
  return {escaped, outside, reply: {open: popup().open, ...pick(spot)}};
})()"""
HOME = """(async () => {@HELPERS@@PROBES@
  const spot = await openSpot();
  const owners = Object.fromEntries(@PARTS@.map((id) => [id, id === "radio" ? spot : spot.querySelector(`[data-panel="${id}"]`)]));
  const pressed = {};
  for (const [id, owner] of Object.entries(owners)) {
    const star = ownStar(owner);
    if (star.getAttribute("aria-pressed") !== "true") {
      star.click();
      await sleep(250);
    }
    pressed[id] = star.getAttribute("aria-pressed");
  }
  await until(() => (ViewStore.get("home.pins") || []).length === 4, 5000);
  const stored = (ViewStore.get("home.pins") || []).map((pin) => [`${pin.kind}:${pin.id}`, pin.w, pin.h]);
  await closeSpot();
  location.hash = "#home";
  await screenShown(8000);
  await until(() => @PARTS@.every((id) => tile(id)) && tile("radio-log").querySelector(".radio-row") && tile("radio").querySelector(".radio-row"), 10000);
  await sleep(400);
  const measure = () => Object.fromEntries(@PARTS@.map((id) => {
    const body = tile(id).querySelector(".home-body");
    const list = tile(id).querySelector(".radio-log");
    const edge = box(body);
    const rows = list ? all(".radio-row", list).filter((row) => box(row).top >= box(list).top - 1 && box(row).bottom <= box(list).bottom + 1).length : null;
    return [id, {scrollers: scrollersIn(tile(id)), rows, inside: list ? box(list).bottom <= edge.bottom + 1 && box(list).top >= edge.top - 1 : null, filled: Math.abs(box(tile(id).querySelector(".radio-home")).height - body.clientHeight + parseFloat(getComputedStyle(body).paddingTop) + parseFloat(getComputedStyle(body).paddingBottom)) <= 2}];
  }));
  const fresh = measure();
  const whole = tile("radio");
  const bar = whole.querySelector(".spot-head");
  const gear = bar ? all("button", bar).find((button) => button.getAttribute("aria-label") === "Read aloud") : null;
  const clear = bar ? all("button", bar).find((button) => button.getAttribute("aria-label") === "Cancel mayday") : null;
  if (gear) {
    gear.click();
    await sleep(200);
  }
  const filters = whole.querySelector(".radio-gear .radio-read");
  const tools = {
    gear: gear ? [gear.getAttribute("aria-expanded"), Boolean(filters), filters ? box(filters).bottom <= box(whole).bottom + 1 : null] : null,
    clear: clear ? [clear.disabled, clear.title] : null,
  };
  if (gear) {
    gear.click();
  }
  const content = {
    tiles: all("#main .home-tile").map((node) => node.dataset.pin),
    radio: [".radio-device", ".radio-speak", ".radio-logbox"].map((selector) => Boolean(tile("radio").querySelector(selector))),
    device: [text(tile("radio-device").querySelector('[data-field="mode"]')), all(".radio-knobs input[type=range]", tile("radio-device")).length],
    speak: [Boolean(tile("radio-speak").querySelector("form.composer textarea")), tile("radio-speak").querySelectorAll("form.composer select option").length > 0],
    log: [tile("radio-log").querySelectorAll(".radio-row").length, tile("radio").querySelectorAll(".radio-row").length, document.querySelectorAll("#radio-spot .radio-row").length],
    gone: all("#main .home-tile.gone").length,
    stars: all("#main .home-tile .home-body .star").length,
    ids: all("#main .home-tile .home-body [id]").map((node) => node.id),
  };
  const count = (id) => tile(id).querySelectorAll(".radio-row").length;
  const before = [count("radio-log"), count("radio")];
  await fetch("/api/voice/@LIVE@", {cache: "no-store"});
  window.dispatchEvent(new Event("focus"));
  const first = (id) => text(tile(id).querySelector(".radio-row .radio-line"));
  const live = await until(() => (count("radio-log") > before[0] && count("radio") > before[1] && first("radio-log").startsWith("live row") ? [first("radio-log"), first("radio")] : null), 20000);
  tile("radio-device").querySelector('.radio-modes button[data-mode="quiet"]').click();
  await sleep(200);
  const mode = [text(tile("radio").querySelector('[data-field="mode"]')), text(document.querySelector('#radio-spot [data-field="mode"]'))];
  tile("radio-device").querySelector('.radio-modes button[data-mode="auto"]').click();
  await sleep(200);
  const sizes = @SIZES@;
  await ViewStore.update("home.pins", (pins) => (pins || []).map((pin) => ({...pin, w: sizes[pin.id][0], h: sizes[pin.id][1]})));
  await until(() => @PARTS@.every((id) => tile(id).dataset.w === String(sizes[id][0]) && tile(id).dataset.h === String(sizes[id][1])), 5000);
  await sleep(400);
  const resized = measure();
  window.scrollTo(0, 0);
  return {pressed, stored, fresh, resized, tools, content, live, mode, wide: document.documentElement.scrollWidth > innerWidth + 1};
})()"""
FIT = """(async () => {@HELPERS@@PROBES@
  await ViewStore.update("home.pins", () => []);
  location.hash = "#agents/orbit";
  await screenShown(8000);
  const spot = await openSpot();
  await until(() => spot.querySelector(".radio-row"), 8000);
  await sleep(500);
  const stage = document.querySelector("#main .stage svg");
  const list = spot.querySelector(".radio-log");
  const result = {
    fit: document.body.classList.contains("fit"), tall: document.documentElement.scrollHeight > innerHeight, wide: document.documentElement.scrollWidth > innerWidth + 1,
    stage: stage ? Math.round(box(stage).height) : 0, height: innerHeight, scrollers: scrollersIn(spot),
    list: list.clientHeight, speak: (() => {
      const card = spot.querySelector(".radio-speak");
      return card.scrollHeight <= card.clientHeight + 1;
    })(),
  };
  await closeSpot();
  await sleep(300);
  const after = document.querySelector("#main .stage svg");
  result.closed = {boxes: spot.getClientRects().length, tall: document.documentElement.scrollHeight > innerHeight, stage: after ? Math.round(box(after).height) : 0};
  return result;
})()"""
SPOT = """(async () => {@HELPERS@@PROBES@@SPEAKING@
  await ViewStore.update("home.pins", () => []);
  location.hash = "@VIEW@";
  await screenShown(8000);
  const spot = await openSpot();
  await until(() => spot.querySelector(".radio-row") && spot.querySelectorAll(".radio-device .station").length === 3, 8000);
  await settle();
  await sleep(500);
  window.scrollTo(0, 0);
  const fits = (node) => node.scrollHeight <= node.clientHeight + 1;
  const list = spot.querySelector(".radio-log");
  const fold = spot.querySelector("details.radio-station");
  const form = spot.querySelector(".radio-speak form.composer");
  const note = form.querySelector(".voice-note");
  const display = spot.querySelector(".radio-caption");
  const named = (node) => node.getAttribute("aria-label") || text(node) || node.getAttribute("title") || `${node.tagName}.${node.getAttribute("class")}`;
  const blocked = () => {
    const layer = spot.querySelector(".radio-station[open] > .station-body");
    const marks = [spot.querySelector(".radio-lamp"), spot.querySelector('[data-field="cpu"]'), spot.querySelector(".radio-device .group-title")];
    const folded = (node) => Boolean(node.closest("details:not([open])")) && !node.closest("summary");
    const found = [];
    for (const node of [...all('button, input, select, textarea, summary, audio, [role="tab"]', spot), ...marks].filter((item) => shown(item) && !folded(item) && box(item).width > 0 && box(item).height > 0)) {
      window.scrollTo(0, 0);
      const seen = box(node);
      if (seen.bottom > innerHeight) {
        window.scrollBy(0, seen.top + seen.height / 2 - innerHeight / 2);
      }
      const edge = box(node);
      const [x, y] = [edge.left + edge.width / 2, edge.top + edge.height / 2];
      const hit = document.elementFromPoint(x, y);
      if (!(list.contains(node) && (y < box(list).top || y > box(list).bottom)) && !(hit === node || node.contains(hit) || (layer && hit && layer.contains(hit) && !layer.contains(node)))) {
        found.push(`${named(node)} <- ${hit ? `${hit.tagName}.${hit.getAttribute("class")}#${hit.id}` : "null"}`);
      }
    }
    window.scrollTo(0, 0);
    return found;
  };
  const stack = () => {
    const card = spot.querySelector(".radio-logbox");
    const head = [card.querySelector(".radio-tabs"), card.querySelector('input[type="search"]')].map(box);
    const chips = all(".chip-select, .radio-filters > button", card).map(box);
    return {head: Math.round(Math.max(...head.map((edge) => edge.bottom))), chips: [Math.round(Math.min(...chips.map((edge) => edge.top))), Math.round(Math.max(...chips.map((edge) => edge.bottom)))], list: Math.round(box(list).top)};
  };
  const measure = () => {
    window.scrollTo(0, 0);
    const [device, speak, history] = ["radio-device", "radio-speak", "radio-log"].map((id) => box(spot.querySelector(`[data-panel="${id}"]`)));
    const svg = document.querySelector("#main .stage svg");
    return {
      fit: document.body.classList.contains("fit"),
      page: [document.documentElement.scrollWidth, document.documentElement.scrollHeight, innerWidth, innerHeight],
      scrollers: scrollersIn(spot), cards: [fits(spot.querySelector(".radio-device")), fits(spot.querySelector(".radio-speak"))],
      main: Math.round(box(document.getElementById("main")).height), floor: Math.round(innerHeight * @MAIN@ - box(document.getElementById("spot-host")).top),
      full: Math.round(innerHeight - document.getElementById("head").offsetHeight - 16), stack: stack(), beneath: box(document.getElementById("main")).top >= box(spot).bottom - 1,
      stage: svg ? Math.round(box(svg).height) : null,
      list: list.clientHeight, rows: all(".radio-row", list).filter((row) => box(row).top >= box(list).top - 1 && box(row).bottom <= box(list).bottom + 1).length,
      order: device.right <= speak.left && device.right <= history.left && speak.bottom <= history.top + 1 && Math.abs(speak.left - history.left) < 2,
      active: {stations: fold.open ? all(".station", fold).filter(shown).length : 0, voice: !note.hidden && shown(note), speech: !display.hidden && shown(display)},
      blocked: blocked(),
      banner: (() => {
        const node = document.getElementById("mayday");
        if (node.hidden || !shown(node)) {
          return null;
        }
        const words = node.querySelector(".text");
        const cancel = node.querySelector("button");
        const edge = box(cancel);
        const hit = document.elementFromPoint(edge.left + edge.width / 2, edge.top + edge.height / 2);
        return {height: Math.round(box(node).height), title: words.title, full: words.textContent, cut: words.scrollWidth > words.clientWidth + 1, cancel: Boolean(hit && cancel.contains(hit))};
      })(),
      play: [note.querySelector(".voice-play"), note.querySelector("audio")].filter((node) => node && shown(node) && box(node).width > 0).map((node) => [node.tagName, Math.round(box(node).width), Math.round(box(node).height)]),
      line: (() => {
        const node = display.querySelector(".caption-line");
        return node && shown(node) ? [Math.round(node.clientWidth), text(node).length] : null;
      })(),
      rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
    };
  };
  const wanted = @STATES@;
  const states = {};
  for (const name of wanted.filter((state) => state === "idle" || state.startsWith("mayday"))) {
    states[name] = measure();
  }
  if (wanted.includes("stations")) {
    const summary = fold.querySelector("summary");
    summary.focus();
    summary.click();
    await sleep(300);
    states.stations = measure();
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
    await sleep(200);
    states.stations.closed = [fold.open, document.activeElement === summary];
  }
  if (wanted.includes("voice")) {
    const record = all("button", form).find((button) => button.hasAttribute("aria-pressed"));
    record.click();
    await sleep(1300);
    record.click();
    const heard = await until(() => !note.hidden && note.querySelector("audio") && form.querySelector("textarea").value, 30000);
    await sleep(300);
    states.voice = {...measure(), heard: Boolean(heard)};
    const toggle = note.querySelector(".voice-play");
    if (toggle && shown(toggle)) {
      toggle.click();
      states.voice.played = Boolean(await until(() => !note.querySelector("audio").paused && toggle.getAttribute("aria-label") === "Pause voice message", 4000));
      toggle.click();
      states.voice.paused = Boolean(await until(() => note.querySelector("audio").paused && toggle.getAttribute("aria-label") === "Play voice message", 4000));
    }
    const trash = all("button", note).find((button) => button.getAttribute("aria-label") === "Remove recording");
    if (trash) {
      trash.click();
    }
    await sleep(200);
  }
  if (wanted.includes("speech")) {
    const found = await cue("@CUE@");
    await sleep(300);
    states.speech = {...measure(), who: found && !found.error ? found.who : found};
    const stop = display.querySelector("button");
    if (stop) {
      stop.click();
    }
    await until(() => display.hidden, 8000);
  }
  return states;
})()"""
