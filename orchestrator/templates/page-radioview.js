  const STATION_TONES = {playing: "ok", loading: "info", reload: "info", blocked: "warn", error: "bad", due: "teal", stopped: "neutral", idle: "neutral", off: "neutral"};
  const NOTE_ID = /^[0-9a-f]{16}$/;
  const MODE_LABELS = {
    auto: ["bi-volume-up", "Auto", "Auto: speech while the host CPU lies below the threshold, otherwise the noise burst"],
    quiet: ["bi-soundwave", "Quiet", "Quiet: the noise burst only, never speech; MAYDAY, PAN-PAN and Sécurité still sound their procedure word"],
    silence: ["bi-volume-mute", "Silence", "Silence: no sound, bubbles and log only; MAYDAY, PAN-PAN and Sécurité still sound their procedure word"],
  };
  const TAB_LABELS = {sent: ["bi-arrow-up-right", "Sent", "Sent: what you transmitted"], received: ["bi-arrow-down-left", "Received", "Received: radio to you or to all"], all: ["bi-journal-text", "All", "All: every radio row the hub logs"]};
  const CHIP_LABELS = {class: "Class", from: "Sender", to: "Recipient", agent: "Agent"};
  let radioDom = null;

  function voiceReplay(note) {
    return typeof note === "string" && NOTE_ID.test(note) ? h("audio", {class: "voice-replay", controls: true, preload: "none", src: `/api/voice/${note}.wav`, "aria-label": "Play voice message"}) : null;
  }

  function daysText(days) {
    return {"0,1,2,3,4,5,6": "daily", "0,1,2,3,4": "weekdays", "5,6": "on weekends"}[days.join(",")] || days.map((day) => WEEKDAYS[day]).join(" ");
  }

  function scheduleOf(stream) {
    return `${daysText(stream.days)}, ${stream.from === "00:00" && stream.to === "24:00" ? "around the clock" : `${stream.from} to ${stream.to}`}`;
  }

  function stationState(stream, index) {
    if (index === radio.index && radio.state) {
      return [radio.state, radio.short, radio.note];
    }
    if (!stream.on) {
      return ["off", "off", "Switched off in the stations"];
    }
    if (!Ambience.activeStream([stream], Ambience.slotOf(new Date()))) {
      return ["idle", "not due", `Plays ${scheduleOf(stream)}; ▶ plays it now`];
    }
    return radio.pick === -1 ? ["stopped", "stopped", "Stopped by hand; ▶ plays it again"] : ["due", "due", "Due as soon as no earlier station plays"];
  }

  function stationRow(stream, index) {
    const [kind, label, note] = stationState(stream, index);
    const live = index === radio.index && (kind === "playing" || kind === "loading");
    const action = live
      ? iconBtn("bi-stop-fill", "Stop", "btn small ghost", stopStation, `Stop: pause ${stream.name}`)
      : iconBtn("bi-play-fill", "Play", "btn small ghost", () => playStation(index), `Play: listen to ${stream.name} now`);
    action.dataset.action = live ? "stop" : "play";
    return h("li", {class: "station", "data-station": index, "data-state": kind},
      h("span", {class: "station-name", title: stream.name}, stream.name),
      h("span", {class: "station-when", title: scheduleOf(stream)}, scheduleOf(stream)),
      h("span", {class: "pill station-note", "data-tone": STATION_TONES[kind], title: note}, label),
      action);
  }

  function drawStations() {
    if (!radioDom) {
      return;
    }
    const sig = JSON.stringify([settings.streams, radio.index, radio.state, radio.note, radio.pick, Math.floor(Date.now() / 60000)]);
    if (sig === radioDom.stationsSig) {
      return;
    }
    radioDom.stationsSig = sig;
    radioDom.stations.replaceChildren(...(settings.streams.length
      ? settings.streams.map(stationRow)
      : [h("li", {class: "muted"}, "No station yet: add one with Edit stations.")]));
  }

  function drawDisplay() {
    if (!radioDom) {
      return;
    }
    const {lamp, cls, mode, cpu} = radioDom.face;
    const now = speech.current;
    const newest = state.radio[state.radio.length - 1];
    const shown = now ? now.cls : newest ? newest.class : "";
    const gate = state.speech.gate;
    const playing = Boolean(now && speech.source);
    const sent = Boolean(playing && now.sent);
    lamp.dataset.lit = String(playing);
    lamp.dataset.tx = String(sent);
    lamp.textContent = sent ? "TX" : "RX";
    lamp.setAttribute("aria-label", playing ? `${sent ? "TX" : "RX"}: sound plays` : "RX: no sound");
    lamp.title = lamp.getAttribute("aria-label");
    cls.textContent = shown ? CLASSES[shown] || shown : "–";
    mode.textContent = MODE_LABELS[radioSet.mode][1];
    cpu.textContent = gate.cpu === null ? "CPU ?" : `CPU ${Math.round(gate.cpu)} %`;
    cpu.dataset.open = String(gate.open);
    cpu.title = gate.cpu === null
      ? `No host CPU sample of the last two minutes: the hub renders no new speech line, threshold ${gate.threshold} %`
      : `Host CPU ${fixed(gate.cpu)} %: new speech renders below ${gate.threshold} %${gate.open ? "" : ", so the radio plays the burst"}`;
  }

  function drawSpeaker() {
    const now = speech.current && speech.current.who ? speech.current : null;
    for (const art of document.querySelectorAll(".avatar[data-face]")) {
      art.classList.toggle("speaking", Boolean(now && art.dataset.face === now.who));
    }
    if (radioDom) {
      const {caption} = radioDom.face;
      caption.hidden = !now;
      caption.replaceChildren(...(now ? [
        h("span", {class: "speaker-face"}, face(now.who, false)),
        h("strong", {}, `${nameOf(now.who)} speaking`),
        h("span", {class: "caption-line", title: now.line}, now.line),
        iconBtn("bi-stop-fill", "Stop speaking", "btn small ghost", cancelSpeech),
      ] : []));
      drawDisplay();
    }
    if (ui.screen === "agents" && (ui.views.agents === "orbit" || ui.views.agents === "chord")) {
      stage();
    }
    drawBubbles();
  }

  function knob(label, hint, attrs, change) {
    const value = h("output", {class: "knob-value"});
    const input = h("input", {type: "range", class: "knob", ...attrs, ...named(label, hint), on: {input: (event) => {
      value.textContent = event.target.value;
      change(Number(event.target.value));
    }}});
    return {input, value, row: h("label", {class: "knob-row", title: hint}, h("span", {class: "knob-label", title: label}, label), input, value)};
  }

  function toneKnob(id, label) {
    const toggle = h("button", {type: "button", class: "btn small ghost icon-only", "aria-pressed": "false", ...named(`${label} tone`), on: {click: () => {
      keepRadio({sounds: {...radioSet.sounds, [id]: {...radioSet.sounds[id], on: !radioSet.sounds[id].on}}});
    }}});
    const level = knob(label, `${label}: tone volume; speech and the burst of these rows play at it`, {min: 0, max: 1, step: 0.05}, (volume) => {
      keepRadio({sounds: {...radioSet.sounds, [id]: {...radioSet.sounds[id], volume}}});
    });
    const test = iconBtn("bi-play-fill", `Test ${label}`, "btn small ghost", () => play(id, loudness(id)), `Test: play the ${label} tone`);
    level.row.prepend(toggle);
    level.row.append(test);
    return {id, toggle, level};
  }

  async function setThreshold(value) {
    if (value !== settings.speech.threshold && await saveSettings({...settings, space: savedSpace(), speech: {threshold: value}})) {
      toast("Speech threshold saved", [`The hub renders new speech only while the host CPU lies below ${value} %.`], true);
    }
    drawRadioSet();
  }

  function knobs() {
    const tones = SOUND_KINDS.map(([id, label]) => toneKnob(id, label));
    const squelch = knob("Squelch", "Squelch: scales every tone, the speech and the burst; 0 plays none", {min: 0, max: 1, step: 0.05}, (value) => keepRadio({squelch: value}));
    const threshold = knob("Threshold", "Speech threshold: the hub renders new speech only while the host CPU lies below it; your passkey signs each change", {min: 30, max: 90, step: 10}, (value) => {
      threshold.value.textContent = `${value} %`;
    });
    threshold.input.addEventListener("change", (event) => setThreshold(Number(event.target.value)));
    const check = iconBtn("bi-broadcast", "Radio check", "btn small ghost", () => say({steps: [{kind: "speech", text: state.speech.sample}], voice: state.speech.operator, tone: "direct", cls: "newsletter", who: HUMAN, sent: true, line: "radio check"}), "Radio check: hear the operator's voice once");
    check.disabled = !state.speech.tts;
    radioDom.knobs = {tones, squelch, threshold, check};
    return [...tones.map((tone) => tone.level.row), squelch.row, threshold.row, h("div", {class: "knob-row"}, check)];
  }

  function faceplate() {
    const lamp = h("span", {class: "radio-lamp", role: "img", "data-lit": "false", "data-tx": "false"}, "RX");
    const field = (name) => h("span", {class: "radio-field", "data-field": name});
    const [cls, mode, cpu] = [field("class"), field("mode"), field("cpu")];
    const caption = h("div", {class: "radio-caption", role: "status", "aria-live": "polite", hidden: true});
    const modes = h("div", {class: "segmented radio-modes", role: "group", "aria-label": "Mode"}, RadioSet.MODES.map((id) => {
      const [name, label, hint] = MODE_LABELS[id];
      return h("button", {type: "button", "data-mode": id, "aria-pressed": "false", ...named(label, hint), on: {click: () => {
        keepRadio({mode: id});
        context();
      }}}, icon(name), label);
    }));
    radioDom.face = {lamp, cls, mode, cpu, caption, modes};
    const display = h("div", {class: "radio-display", role: "group", "aria-label": "Display"}, lamp, cls, mode, cpu);
    return h("div", {class: "radio-face", role: "group", "aria-label": "Radio set"}, display, caption, modes, h("div", {class: "radio-knobs", role: "group", "aria-label": "Knobs"}, knobs()));
  }

  function radioFilters() {
    const chip = (label, pressed, hint, run, locked) => h("button", {type: "button", class: "chip", "aria-pressed": String(pressed), disabled: locked, ...named(label, hint), on: {click: run}}, label);
    const classes = SPEECH_CLASSES.map(([id, label]) => chip(label, radioSet.classes.includes(id), id === "mayday" ? "MAYDAY always sounds" : `Read ${label} aloud`, () => {
      keepRadio({classes: radioSet.classes.includes(id) ? radioSet.classes.filter((name) => name !== id) : [...radioSet.classes, id]});
      redrawFilters();
    }, id === "mayday"));
    const agents = Object.entries(people()).sort(([, a], [, b]) => a.now.localeCompare(b.now)).map(([key, entry]) => chip(entry.now, !radioSet.muted.includes(key), `Read ${entry.now} aloud`, () => {
      keepRadio({muted: radioSet.muted.includes(key) ? radioSet.muted.filter((name) => name !== key) : [...radioSet.muted, key]});
      redrawFilters();
    }, false));
    return h("div", {class: "radio-read", "aria-label": "Read aloud"},
      h("p", {class: "muted"}, state.speech.tts ? "The radio sounds for these classes and agents, each speaker with its own voice; MAYDAY always sounds." : `The hub speaks no line: ${state.speech.tts_off}. The burst and the procedure words stand in.`),
      h("div", {class: "chips", role: "group", "aria-label": "Classes"}, classes),
      agents.length ? h("div", {class: "chips", role: "group", "aria-label": "Agents"}, agents) : null);
  }

  function redrawFilters() {
    if (spotDom && !spotDom.gearBox.hidden) {
      spotDom.gearBox.replaceChildren(radioFilters());
    }
  }

  function keepLog(change) {
    keepRadio({log: {...radioSet.log, ...change}});
  }

  function chipSelect(name, values) {
    const chosen = radioSet.log.chips[name];
    const label = CHIP_LABELS[name];
    const options = [...new Set([...values, ...(chosen ? [chosen] : [])])];
    const select = h("select", {class: "field", "aria-label": label, title: `${label}: filter the log`, on: {change: (event) => keepLog({chips: {...radioSet.log.chips, [name]: event.target.value}})}},
      h("option", {value: ""}, `${label}: any`), options.map((value) => h("option", {value, selected: value === chosen}, name === "class" ? CLASSES[value] || value : value)));
    return h("label", {class: "chip-select", "data-chip": name, "data-active": String(Boolean(chosen))}, select);
  }

  function logLine(row) {
    const message = row.sent ? row : RadioSet.ledgerOf(row, state.messages);
    const sent = Boolean(message);
    const [name, label] = sent ? ["bi-arrow-up-right", "Sent"] : ["bi-arrow-down-left", "Received"];
    const first = row.text.split("\n").map((part) => part.trim()).find(Boolean) || "";
    return h("li", {class: "radio-row", "data-dir": sent ? "sent" : "received", "data-class": row.class},
      h("details", {}, h("summary", {},
        when(row.ts),
        h("span", {class: "radio-dir", role: "img", ...named(label)}, icon(name)),
        klass(row.class),
        h("span", {class: "radio-route"}, `${row.from} → ${targetsOf(row)}`),
        h("span", {class: "radio-line", title: first}, first)),
      h("pre", {class: "radio-full"}, row.text),
      voiceReplay(message ? message.voice : null)));
  }

  function drawLog() {
    const dom = radioDom.log;
    const entry = radioSet.log;
    const sig = JSON.stringify([state.radio.length, state.radio.length ? state.radio[state.radio.length - 1].ts : 0, state.messages.length, entry, Math.floor(Date.now() / 60000)]);
    if (sig === dom.sig) {
      return;
    }
    dom.sig = sig;
    const counts = RadioSet.counts(state.radio, HUMAN, state.messages);
    dom.tabs.replaceChildren(...RadioSet.TABS.map((tab) => {
      const [name, label, hint] = TAB_LABELS[tab];
      return h("button", {type: "button", role: "tab", "data-tab": tab, "aria-selected": String(tab === entry.tab), title: hint, on: {click: () => keepLog({tab})}},
        icon(name), label, h("span", {class: "count", "aria-label": `${counts[tab]} rows`}, String(counts[tab])));
    }));
    const choices = RadioSet.choices(state.radio);
    dom.chips.replaceChildren(...RadioSet.CHIPS.map((name) => chipSelect(name, choices[name])));
    if (document.activeElement !== dom.search && dom.search.value !== entry.q) {
      dom.search.value = entry.q;
    }
    const rows = RadioSet.logRows(state.radio, entry, HUMAN, state.messages);
    dom.list.replaceChildren(...(rows.length ? rows.map(logLine) : [h("li", {class: "muted"}, state.radio.length ? "No radio row matches the tab, the chips and the search." : "No radio in the chosen time range yet.")]));
  }

  function radioLog() {
    const tabs = h("div", {class: "radio-tabs", role: "tablist", "aria-label": "Log"});
    const chips = h("div", {class: "radio-chips", role: "group", "aria-label": "Log filters"});
    const search = h("input", {type: "search", class: "field", placeholder: "Search the log …", maxlength: 200, ...named("Search the log"), on: {input: (event) => keepLog({q: event.target.value})}});
    const clear = iconBtn("bi-x-circle", "Clear filters", "btn small ghost", () => keepRadio({log: RadioSet.cleared(radioSet.log)}), "Clear filters: every chip and the search");
    const list = h("ul", {class: "radio-log", "aria-label": "Radio log"});
    radioDom.log = {tabs, chips, search, list, sig: ""};
    return h("section", {class: "radio-logbox", "aria-label": "Radio log"}, tabs, h("div", {class: "radio-filters"}, chips, search, clear), list);
  }

  function drawRadioSet() {
    if (!radioDom) {
      return;
    }
    for (const button of radioDom.face.modes.querySelectorAll("button[data-mode]")) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === radioSet.mode));
    }
    const {tones, squelch, threshold} = radioDom.knobs;
    for (const {id, toggle, level} of tones) {
      const sound = radioSet.sounds[id];
      toggle.setAttribute("aria-pressed", String(sound.on));
      toggle.replaceChildren(icon(sound.on ? "bi-bell" : "bi-bell-slash"));
      toggle.title = `${toggle.getAttribute("aria-label")}: ${sound.on ? "on, a press mutes it" : "off, a press turns it on"}`;
      level.input.value = String(sound.volume);
      level.value.textContent = sound.volume.toFixed(2);
    }
    squelch.input.value = String(radioSet.squelch);
    squelch.value.textContent = radioSet.squelch.toFixed(2);
    threshold.input.value = String(settings.speech.threshold);
    threshold.value.textContent = `${settings.speech.threshold} %`;
    drawDisplay();
    drawLog();
  }

  function drawRadio() {
    if (!radioDom) {
      return;
    }
    drawRadioSet();
    drawStations();
  }

  function radioSide() {
    const stations = h("ul", {class: "stations", "aria-label": "Stations"});
    radioDom = {stations, stationsSig: ""};
    const face = faceplate();
    const log = radioLog();
    const station = h("section", {class: "radio-station", "aria-label": "Internet radio"}, h("div", {class: "card-head"}, h("h3", {class: "group-title"}, "Internet radio"), btn("Edit stations", "btn small ghost", stationsSheet)), stations);
    window.setTimeout(drawRadio, 0);
    return {face, log, station};
  }
