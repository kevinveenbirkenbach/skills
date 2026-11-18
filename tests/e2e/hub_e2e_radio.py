from __future__ import annotations

import contextlib
import http.server

from hub_e2e_kit import FITS, HELPERS, OVERLAP, SPEAKING

CALL = """(async () => {@HELPERS@
  document.querySelector('#main [aria-label="Categories"] button[aria-label="Radio"]').click();
  const someone = await until(() => document.querySelector('#main button.linkish[title^="Open "]'), 8000);
  someone.click();
  await sleep(500);
  document.querySelector('#popup input[type=radio][value="call"]').click();
  const field = document.querySelector("#popup textarea");
  field.value = "E2E call ping";
  field.dispatchEvent(new Event("input", {bubbles: true}));
  document.querySelector('#popup button[type="submit"]').click();
  const entry = await until(() => all("#main .entry").find((row) => row.textContent.includes("E2E call ping") && row.querySelector('.reader[data-acked="true"] .ack')), 20000);
  const read = all("#main .entry .pill").filter((pill) => text(pill) === "Read").length;
  return {to: text(someone), receipt: entry ? entry.querySelector('.reader[data-acked="true"]').title : null, read, sent: all("#main .entry").filter((row) => row.textContent.includes("E2E call ping")).length};
})()""".replace("@HELPERS@", HELPERS)
MEDIA_LOG = """() => {
  const keep = (entry) => {
    try {
      const list = JSON.parse(sessionStorage.getItem("e2e-media") || "[]");
      list.push({...entry, page: Math.round(performance.timeOrigin)});
      sessionStorage.setItem("e2e-media", JSON.stringify(list));
    } catch (error) {
      return;
    }
  };
  const play = HTMLMediaElement.prototype.play;
  window.e2eMedia = new Set();
  HTMLMediaElement.prototype.play = function () {
    window.e2eAudio = this;
    window.e2eMedia.add(this);
    const src = this.getAttribute("src") || "";
    const result = play.call(this);
    result.then(() => keep({play: "ok", src}), (error) => keep({play: error.name, src}));
    return result;
  };
  document.addEventListener("securitypolicyviolation", (event) => keep({csp: event.effectiveDirective, blocked: event.blockedURI}));
}"""
MEDIA = """
  const log = () => JSON.parse(sessionStorage.getItem("e2e-media") || "[]");
  const sample = () => (window.e2eAudio ? {paused: window.e2eAudio.paused, time: window.e2eAudio.currentTime, error: window.e2eAudio.error ? window.e2eAudio.error.code : null, src: window.e2eAudio.getAttribute("src")} : null);
  const advancing = async () => {
    const first = sample();
    await sleep(1500);
    const second = sample();
    return {first, second, playing: Boolean(first && second && !second.paused && second.time - first.time > 0.5)};
  };
"""
ADD_STATION = """(async () => {@HELPERS@
  const clock = (date) => `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  location.hash = "#stream/radio";
  const fold = await until(() => document.querySelector("#radio-spot details.radio-station"), 8000);
  fold.open = true;
  const edit = await until(() => all("#radio-spot button").find((button) => text(button) === "Edit stations" && button.getClientRects().length), 8000);
  edit.click();
  const form = await until(() => document.querySelector('.sheet-box form[aria-label="Stations"]'), 8000);
  all("button", form).find((button) => text(button) === "+ Station").click();
  await sleep(200);
  const row = all(".stream-row", form).pop();
  const [label, address, start, end] = all("input.field", row);
  const set = (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event("input", {bubbles: true}));
  };
  set(label, "@NAME@");
  set(address, "@STATION@");
  set(start, clock(new Date(Date.now() - 3600000)));
  set(end, clock(new Date(Date.now() + 3600000)));
  all('.days input[type="checkbox"]', row).forEach((box) => {
    box.checked = true;
  });
  all("button", form).find((button) => button.type === "submit").click();
  await until(() => all("#toasts .toast").map(text).find((toast) => toast.startsWith("New station")), 8000);
  return {toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS)
STATION_NAME = "E2E tone with a very long station name that fits on no single line"
DLF_PATH = "/dlf/01/high/aac/stream.aac?aggregator=web"
DLF_NODE = "/ard/dlf/01/aac/192/stream.aac?aggregator=web"
RADIO_STATE = """(async () => {@HELPERS@@MEDIA@
  await until(() => log().some((entry) => entry.play), 8000);
  return {log: log(), media: await advancing(), toasts: all("#toasts .toast").map(text)};
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
RADIO_VIEW = """(async () => {@HELPERS@@MEDIA@
  location.hash = "#stream/radio";
  const fold = await until(() => document.querySelector("#radio-spot details.radio-station"), 8000);
  fold.open = true;
  const row = await until(() => all('#radio-spot [data-station="0"]').find((item) => item.getClientRects().length), 8000);
  if (!row) {
    const initial = JSON.parse(document.getElementById("state").textContent);
    return {error: "no station row", log: log(), wrapped: !String(HTMLMediaElement.prototype.play).includes("[native code]"), streams: initial.settings.streams, media: initial.media, now: new Date().toString()};
  }
  const label = row.querySelector(".station-name");
  const style = getComputedStyle(label);
  return {
    state: row.dataset.state,
    note: text(row.querySelector(".station-note")),
    title: label.title,
    line: [style.whiteSpace, style.textOverflow, label.scrollWidth > label.clientWidth, label.getBoundingClientRect().height < 2 * parseFloat(style.lineHeight)],
    media: await advancing(),
    log: log(),
    toasts: all("#toasts .toast").map(text),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
RADIO_CLICK = """(async () => {@HELPERS@@MEDIA@
  const row = document.querySelector('#radio-spot [data-station="0"]');
  if (!row) {
    return {error: "no station row", log: log(), media: await advancing()};
  }
  const play = row.querySelector('button[data-action="play"]');
  const clicked = Boolean(sample() && sample().paused && play);
  if (clicked) {
    play.click();
  }
  await until(() => sample() && !sample().paused, 6000);
  const media = await advancing();
  const now = document.querySelector('#radio-spot [data-station="0"]');
  return {clicked, state: now.dataset.state, note: text(now.querySelector(".station-note")), media, log: log()};
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
RADIO_STOP = """(async () => {@HELPERS@@MEDIA@
  const row = () => document.querySelector('#radio-spot [data-station="0"]');
  const stop = row() ? row().querySelector('button[data-action="stop"]') : null;
  if (!stop) {
    return {error: "no Stop button on the playing station", state: row() ? row().dataset.state : null, media: sample(), log: log()};
  }
  const button = [stop.getAttribute("aria-label"), stop.title, text(stop), Boolean(stop.querySelector('svg.bi use[href="#bi-stop-fill"]'))];
  stop.click();
  const paused = Boolean(await until(() => sample() && sample().paused && sample().src === null, 8000));
  const media = await advancing();
  const now = row();
  const action = now ? now.querySelector("button[data-action]") : null;
  const elements = [...new Set([...(window.e2eMedia || []), ...all("audio, video")])];
  return {
    button, paused, media, tracked: (window.e2eMedia || new Set()).size,
    state: now ? now.dataset.state : null, note: now ? text(now.querySelector(".station-note")) : null,
    action: action ? [action.dataset.action, action.getAttribute("aria-label")] : null,
    playing: elements.filter((element) => !element.paused).map((element) => element.getAttribute("src") || element.currentSrc || element.tagName),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@MEDIA@", MEDIA)
SPEAK = """(async () => {@HELPERS@@SPEAKING@
  return cue("@CUE@");
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
SPEAK_GRAPH = """(async () => {@HELPERS@@SPEAKING@
  location.hash = "#agents/orbit";
  const node = await until(() => document.querySelector("#main svg .node.speaking"), 6000);
  const silent = document.querySelector('#main svg .node[data-pick="s1"] .mouth');
  return {
    node: node ? node.getAttribute("aria-label") : null, ring: node ? getComputedStyle(node.querySelector("circle")).animationName : null,
    mouth: node ? getComputedStyle(node.querySelector(".mouth")).animationName : null, silent: silent ? getComputedStyle(silent).animationName : null,
  };
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
SPEAK_END = """(async () => {@HELPERS@@SPEAKING@
  const ended = Boolean(await until(() => !document.querySelector("#main svg .node") || !document.querySelector("#main svg .node.speaking"), 20000));
  location.hash = "#stream/radio";
  await until(() => document.querySelector("#radio-spot:not([hidden]) .radio-caption"), 6000);
  await sleep(300);
  return {ended, caption: Boolean(caption()), faces: all(".avatar.speaking").length};
})()""".replace("@HELPERS@", HELPERS).replace("@SPEAKING@", SPEAKING)
SPOT_OPEN = """
  const spotToggle = document.getElementById("radio-open");
  if (spotToggle && spotToggle.getAttribute("aria-expanded") !== "true") {
    spotToggle.click();
    await sleep(300);
  }
  const spot = document.getElementById("radio-spot");
"""
COMPOSE = """(async () => {@HELPERS@@SPOT_OPEN@
  const form = spot ? spot.querySelector("form.composer") : null;
  if (!form) {
    return {error: "no composer"};
  }
  const [channel, recipient] = all("select", form);
  await until(() => [...recipient.options].some((option) => option.value === "@TO@"), 8000);
  channel.value = "call";
  channel.dispatchEvent(new Event("change", {bubbles: true}));
  recipient.value = "@TO@";
  const record = all("button", form).find((button) => button.hasAttribute("aria-pressed") && !button.classList.contains("mic"));
  record.click();
  await sleep(1500);
  const recording = record.getAttribute("aria-pressed");
  record.click();
  const field = form.querySelector("textarea");
  await until(() => field.value && form.querySelector('.voice-note input[type="checkbox"]'), 60000);
  const replay = form.querySelector(".voice-note audio");
  const attach = form.querySelector('.voice-note input[type="checkbox"]');
  return {
    channels: all("option", channel).map((option) => option.value),
    recipients: all("option", recipient).map((option) => option.value),
    recording,
    text: field.value,
    replay: replay ? replay.getAttribute("src") : null,
    attach: attach ? [text(attach.closest("label")), attach.checked] : null,
    status: text(form.querySelector(".composer-status")),
    toasts: all("#toasts .toast").map(text),
    clashes: (() => {@CLASHES@
      return clashes(form);
    })(),
  };
})()""".replace("@HELPERS@", HELPERS).replace("@SPOT_OPEN@", SPOT_OPEN).replace("@CLASHES@", OVERLAP)
COMPOSE_SEND = """(async () => {@HELPERS@
  const form = document.querySelector("#radio-spot form.composer");
  const field = form.querySelector("textarea");
  field.value = `${field.value} please`;
  field.dispatchEvent(new Event("input", {bubbles: true}));
  form.querySelector('.voice-note input[type="checkbox"]').checked = @ATTACH@;
  const before = all("#toasts .toast").length;
  form.querySelector('button[type="submit"]').click();
  const sent = await until(() => all("#toasts .toast").slice(before).map(text).find((toast) => toast.startsWith("Call to")), 20000);
  return {sent, left: field.value, voice: Boolean(form.querySelector(".voice-note audio"))};
})()""".replace("@HELPERS@", HELPERS)
CLEAR_MAYDAY = """(async () => {@HELPERS@
  const questions = [];
  let accept = false;
  window.confirm = (question) => {
    questions.push(question);
    return accept;
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).startsWith("/api/board/")) {
      posted.push(String(path));
    }
    return send(path, init);
  };
  await until(() => document.querySelector('#main [role="toolbar"]'), 8000);
  const toolbar = all('#main [role="toolbar"] button, #main [role="toolbar"] summary').map(name);@SPOT_OPEN@
  const button = await until(() => spot && all("form.composer .radio-cancel", spot).find((node) => name(node) === "Cancel mayday" && !node.hidden), 8000);
  if (!button) {
    return {error: "no shown Cancel mayday button next to PTT", toolbar};
  }
  const shown = new Set(all("#toasts .toast"));
  const fresh = () => all("#toasts .toast").filter((node) => !shown.has(node)).map(text);
  button.click();
  await sleep(800);
  const declined = {question: questions.slice(), posted: posted.slice(), toasts: fresh()};
  accept = true;
  button.click();
  const done = await until(() => fresh().find((toast) => toast.startsWith("Cancel mayday")), 15000);
  return {toolbar, title: button.title, shown: text(button), declined, accepted: {question: questions.slice(declined.question.length), posted: posted.slice(declined.posted.length)}, done};
})()""".replace("@HELPERS@", HELPERS).replace("@SPOT_OPEN@", SPOT_OPEN)
SPOT_SEND = """(async () => {@HELPERS@
  const questions = [];
  window.confirm = (question) => {
    questions.push(question);
    return true;
  };
  await until(() => document.querySelector('#main [role="toolbar"]'), 8000);
  const toggle = document.getElementById("radio-open");
  const main = document.getElementById("main");
  const spot = document.getElementById("radio-spot");
  const closed = [spot.hidden, toggle.getAttribute("aria-expanded")];
  toggle.click();
  await sleep(400);
  const form = spot.querySelector("form.composer");
  const [channel, recipient] = all("select", form);
  const field = form.querySelector("textarea");
  const found = {
    closed,
    open: [spot.hidden, toggle.getAttribute("aria-expanded"), document.activeElement === field],
    inline: [getComputedStyle(spot).position, spot.getBoundingClientRect().bottom <= main.getBoundingClientRect().top, spot.parentElement.nextElementSibling === main],
    toolbar: all('#main [role="toolbar"] > *').map((node) => name(node.tagName === "DETAILS" ? node.querySelector("summary") : node)),
    channels: all("option", channel).map((option) => option.value),
    record: all("button", form).filter((button) => button.hasAttribute("aria-pressed") && !button.classList.contains("mic")).map(text),
    heads: all(".spot-head button", spot).length,
    send: all(".ptt-split :is(button, summary)", form).filter((node) => !node.closest(".menu-box")).map((node) => [name(node), node.title]),
    cancel: form.querySelector(".radio-cancel").hidden,
    @FITS@,
  };
  await until(() => [...recipient.options].some((option) => option.value === "Stage"), 8000);
  found.runs = [];
  for (const cls of found.channels) {
    channel.value = cls;
    channel.dispatchEvent(new Event("change", {bubbles: true}));
    const direct = !recipient.closest("label").hidden;
    if (direct) {
      recipient.value = "Stage";
    }
    field.value = `@TEXT@ ${cls}`;
    field.dispatchEvent(new Event("input", {bubbles: true}));
    const shown = new Set(all("#toasts .toast"));
    const prompts = questions.length;
    const submit = form.querySelector('button[type="submit"]');
    submit.click();
    const toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((entry) => entry.includes(" to ")), 20000);
    await until(() => !submit.disabled, 20000);
    found.runs.push({cls, direct, toast, question: questions.slice(prompts), left: field.value});
  }
  document.getElementById("toasts").replaceChildren();
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@FITS@", FITS)
RADIO_JUMP = """(async () => {@HELPERS@
  const spot = await until(() => location.hash === "#stream" && document.querySelector("#radio-spot:not([hidden])"), 8000);
  if (!spot) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(200);
  const focused = document.activeElement === spot.querySelector("textarea");
  const tabs = [];
  for (const hash of ["#home", "#stream/inbox", "#agents/orbit", "#artifacts/tree", "#tasks/list", "#resources"]) {
    location.hash = hash;
    await sleep(500);
    const main = document.getElementById("main");
    tabs.push([hash, !spot.hidden, spot.getBoundingClientRect().bottom <= main.getBoundingClientRect().top]);
  }
  const toggle = document.getElementById("radio-open");
  toggle.click();
  await sleep(200);
  return {
    hash: "#stream", focused, tabs, closed: [spot.hidden, toggle.getAttribute("aria-expanded")],
    header: all("header.top button[id]").map((button) => [button.id, name(button), text(button)]), radioTab: Boolean(document.getElementById("tab-radio")),
  };
})()""".replace("@HELPERS@", HELPERS)
CANCELED = """() => {
  window.e2ePasskeys = 0;
  if (navigator.credentials) {
    navigator.credentials.get = () => {
      window.e2ePasskeys += 1;
      return Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
    };
  }
}"""
JUMPED = {
    "hash": "#stream", "focused": True, "tabs": [[tab, True, True] for tab in ("#home", "#stream/inbox", "#agents/orbit", "#artifacts/tree", "#tasks/list", "#resources")], "closed": [True, "false"],
    "header": [["grant-select", "Select", "Select"], ["radio-open", "Radio", ""], ["bubbles-toggle", "Speech bubbles", ""], ["palette-open", "Commands", ""], ["settings-open", "Settings", ""]], "radioTab": False,
}
BELLS = """
  const bell = (label) => spot.querySelector(`.radio-face button[aria-label="${label} tone"]`);
  const ring = async (label, want) => {
    for (let press = 0; press < 3 && bell(label).dataset.bell !== want; press += 1) {
      bell(label).click();
      await sleep(100);
    }
  };
"""
BELL_SAVE = """(async () => {@HELPERS@@CLASHES@@BELLS@
  const spot = document.getElementById("radio-spot");
  const face = spot.querySelector(".radio-face");
  const found = {
    tones: all(".radio-knobs .knob-label", face).map(text),
    bells: all(".radio-knobs .knob-toggle", face).map((button) => name(button)),
    clashes: [clashes(face)],
    @FITS@,
  };
  const squelch = face.querySelector('input[aria-label="Squelch"]');
  squelch.value = "@SQUELCH@";
  squelch.dispatchEvent(new Event("input", {bubbles: true}));
  await ring("All radio", "@RADIO@");
  await ring("Post and calls to you", "@POST@");
  await sleep(200);
  const kept = JSON.parse(localStorage.getItem("kvb-orchestrator.radio"));
  found.kept = [kept.squelch, kept.sounds.radio.on, kept.classes.includes("post")];
  found.after = [bell("All radio").dataset.bell, bell("Post and calls to you").dataset.bell];
  document.getElementById("settings-open").click();
  const sheet = await until(() => document.querySelector(".sheet-box form.settings"), 4000);
  found.general = {sections: all("section > h3", sheet).map(text), radio: all('[aria-label="Squelch"], [aria-label="Classes"], [aria-label="Speakers"], [aria-label="Mode"], .sound-row, .stream-row', sheet).length};
  document.querySelector(".sheet-head button").click();
  return found;
})()""".replace("@HELPERS@", HELPERS).replace("@CLASHES@", OVERLAP).replace("@BELLS@", BELLS).replace("@FITS@", FITS)
BELL_READ = """(async () => {@HELPERS@@SPOT_OPEN@@BELLS@
  const face = spot ? spot.querySelector(".radio-face") : null;
  if (!face) {
    return {error: text(document.getElementById("main"))};
  }
  return {
    squelch: Number(face.querySelector('input[aria-label="Squelch"]').value),
    radio: bell("All radio").dataset.bell,
    post: bell("Post and calls to you").dataset.bell,
    @FITS@,
  };
})()""".replace("@HELPERS@", HELPERS).replace("@SPOT_OPEN@", SPOT_OPEN).replace("@BELLS@", BELLS).replace("@FITS@", FITS)


class Station(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.server.moved:
            self.send_response(302)
            self.send_header("Location", self.server.moved)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = self.server.body
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return
