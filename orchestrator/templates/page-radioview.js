  const STATION_TONES = {playing: "ok", loading: "info", reload: "info", blocked: "warn", error: "bad", due: "teal", stopped: "neutral", idle: "neutral", off: "neutral"};
  const NOTE_ID = /^[0-9a-f]{16}$/;
  const MODE_LABELS = {
    auto: ["bi-volume-up", "Auto", "Auto: speech while the host CPU lies below the threshold, otherwise the fallback picked under Read aloud"],
    quiet: ["bi-soundwave", "Quiet", "Quiet: the fallback picked under Read aloud, never speech; MAYDAY, PAN-PAN and Sécurité still sound their procedure word"],
    silence: ["bi-volume-mute", "Silence", "Silence: no sound, bubbles and log only; MAYDAY, PAN-PAN and Sécurité still sound their procedure word"],
    morse: ["bi-three-dots", "Morse", "Morse: every message keyed whole in Morse, in its sender's own pitch, at the hub's Morse speed; MAYDAY keys SOS"],
    gibberlink: ["bi-robot", "Gibberlink", "Gibberlink: every message sent whole as ggwave data sound a machine can decode, in its sender's own protocol and stereo position; MAYDAY, PAN-PAN and Sécurité still sound their procedure word"],
  };
  const FALLBACK_LABELS = {
    gibberlink: ["Gibberlink", "Where speech cannot play, send the rest as ggwave data sound"],
    morse: ["Morse", "Where speech cannot play, key the whole message in Morse"],
    burst: ["Hiss", "Where speech cannot play, play the short noise burst"],
  };
  const radioParts = {bars: [], devices: [], logs: [], speaks: []};
  const liveParts = (kind) => radioParts[kind].filter((part) => part.root.isConnected);

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

  function nowPlaying() {
    const stream = settings.streams[radio.index];
    if (!stream || !radio.state) {
      return null;
    }
    const [kind, label] = stationState(stream, radio.index);
    return h("span", {class: "pill station-now", "data-tone": STATION_TONES[kind], title: `${stream.name}: ${label}`}, label);
  }

  function drawStations() {
    const sig = JSON.stringify([settings.streams, radio.index, radio.state, radio.note, radio.pick, Math.floor(Date.now() / 60000)]);
    for (const part of liveParts("devices")) {
      if (sig === part.stationsSig) {
        continue;
      }
      part.stationsSig = sig;
      part.now.replaceChildren(...[nowPlaying()].filter(Boolean));
      part.stations.replaceChildren(...(settings.streams.length
        ? settings.streams.map(stationRow)
        : [h("li", {class: "muted"}, "No station yet: add one with Edit stations.")]));
    }
  }

  function drawDisplay() {
    const now = speech.current;
    const newest = state.radio[state.radio.length - 1];
    const shown = now ? now.cls : newest ? newest.class : "";
    const gate = state.speech.gate;
    const playing = Boolean(now && speech.source);
    const sent = Boolean(playing && now.sent);
    for (const part of liveParts("devices")) {
      const {lamp, cls, mode, cpu} = part.face;
      lamp.dataset.lit = String(playing);
      lamp.dataset.tx = String(sent);
      lamp.textContent = sent ? "TX" : "RX";
      lamp.setAttribute("aria-label", playing ? `${sent ? "TX" : "RX"}: sound plays` : "RX: no sound");
      lamp.title = lamp.getAttribute("aria-label");
      cls.textContent = shown ? CLASSES[shown] || shown : "–";
      mode.textContent = MODE_LABELS[radioSet.mode][1];
      cpu.textContent = gate.cpu === null ? "CPU ?" : `CPU ${Math.round(gate.cpu)} %`;
      cpu.dataset.open = String(gate.open);
      cpu.title = `${gate.cpu === null ? "No host CPU sample of the last two minutes" : `Host CPU ${fixed(gate.cpu)} %`}, threshold: ${RadioSet.gateLabel(gate.threshold)}${gate.open ? "" : ", so the hub renders no new speech line and the radio plays the fallback"}`;
    }
  }

  function drawSpeaker() {
    const now = speech.current && speech.current.who ? speech.current : null;
    for (const art of document.querySelectorAll(".avatar[data-face]")) {
      art.classList.toggle("speaking", Boolean(now && art.dataset.face === now.who));
    }
    for (const part of liveParts("devices")) {
      const {caption} = part.face;
      caption.hidden = !now;
      caption.replaceChildren(...(now ? [
        h("span", {class: "speaker-face"}, face(now.who, false)),
        h("strong", {}, nameOf(now.who), h("span", {class: "caption-verb"}, " speaking")),
        h("span", {class: "caption-line", title: now.line}, now.line),
        iconBtn("bi-stop-fill", "Stop speaking", "btn small ghost", cancelSpeech),
      ] : []));
    }
    drawDisplay();
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
    const name = h("span", {class: "knob-label", title: label}, label);
    return {input, value, name, row: h("div", {class: "knob-row", title: hint}, name, input, value)};
  }

  function toneKnob(id, label) {
    const toggle = h("button", {type: "button", class: "btn small ghost icon-only knob-toggle", "aria-pressed": "false", ...named(`${label} tone`), on: {click: () => {
      keepRadio({sounds: {...radioSet.sounds, [id]: {...radioSet.sounds[id], on: !radioSet.sounds[id].on}}});
    }}});
    const level = knob(label, `${label}: tone volume; speech and the burst of these rows play at it`, {min: 0, max: 1, step: 0.05}, (volume) => {
      keepRadio({sounds: {...radioSet.sounds, [id]: {...radioSet.sounds[id], volume}}});
    });
    const test = iconBtn("bi-play-fill", `Test ${label}`, "btn small ghost knob-test", () => play(id, loudness(id)), `Test: play the ${label} tone`);
    level.row.prepend(toggle);
    level.row.append(test);
    return {id, toggle, level};
  }

  async function setThreshold(value) {
    if (value !== settings.speech.threshold && await saveSettings({...settings, space: savedSpace(), speech: {threshold: value}})) {
      toast("Speech threshold saved", [`The hub renders new speech: ${RadioSet.gateLabel(value)}.`], true);
    }
    drawRadioSet();
  }

  function drawGate(gate, value) {
    gate.name.textContent = RadioSet.gateLabel(value);
    gate.name.title = gate.name.textContent;
    gate.value.textContent = `${value} %`;
    gate.input.setAttribute("aria-valuetext", gate.name.textContent);
  }

  function knobs() {
    const tones = SOUND_KINDS.map(([id, label]) => toneKnob(id, label));
    const squelch = knob("Squelch", "Squelch: scales every tone, the speech and the burst; 0 plays none", {min: 0, max: 1, step: 0.05}, (value) => keepRadio({squelch: value}));
    squelch.row.append(iconBtn("bi-play-fill", "Test Squelch", "btn small ghost knob-test", () => say({steps: [{kind: "burst"}], voice: "", tone: "radio", cls: "post", who: HUMAN, sent: true, line: "squelch test"}), "Test: play the burst of a radio row, at the All radio volume times the squelch"));
    const threshold = knob("Threshold", "Speech threshold: the hub renders new speech only while the host CPU lies below it, always at 100 %, never at 0 %; your passkey signs each change", RadioSet.GATE, (value) => drawGate(threshold, value));
    threshold.input.addEventListener("change", (event) => setThreshold(Number(event.target.value)));
    const check = iconBtn("bi-broadcast", "Radio check", "btn small ghost radio-check", () => say({steps: [{kind: "speech", text: state.speech.sample}], voice: state.speech.operator, tone: "direct", cls: "newsletter", who: HUMAN, sent: true, line: "radio check"}), "Radio check: hear the operator's voice once");
    check.disabled = !state.speech.tts;
    return {tones, squelch, threshold, check, rows: [...tones.map((tone) => tone.level.row), squelch.row, threshold.row]};
  }

  function faceplate(part) {
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
    part.face = {lamp, cls, mode, cpu, caption, modes};
    part.knobs = knobs();
    const display = h("div", {class: "radio-display", role: "group", "aria-label": "Display"}, lamp, cls, mode, cpu);
    return h("div", {class: "radio-face", role: "group", "aria-label": "Radio set"}, display, caption, modes, part.knobs.check,
      h("div", {class: "radio-knobs", role: "group", "aria-label": "Knobs"}, part.knobs.rows));
  }

  function toggleGear(part) {
    const open = part.box.hidden;
    part.box.replaceChildren(...(open ? [radioFilters()] : []));
    part.box.hidden = !open;
    part.gear.setAttribute("aria-expanded", String(open));
    window.requestAnimationFrame(refresh3d);
  }

  /**
   * @param {boolean} spot whether the bar heads the radio spot.
   * @returns {object} the bar part: root, gear, its box and the Cancel mayday button.
   */
  function radioBar(spot) {
    const part = {box: h("div", {class: "radio-gear", id: spot ? "radio-gear" : null, hidden: true})};
    part.gear = iconBtn("bi-funnel", "Read aloud", "btn small ghost spot-toggle", () => toggleGear(part), "Read aloud: the classes and agents the radio sounds for");
    part.gear.setAttribute("aria-expanded", "false");
    if (spot) {
      part.gear.setAttribute("aria-controls", "radio-gear");
    }
    const [, label, , hint] = actionOf("clear-mayday");
    part.clear = iconBtn("bi-life-preserver", label, "btn small danger", () => confirmAct("clear-mayday", []), hint);
    part.clear.disabled = !state.silence;
    part.root = h("div", {class: "spot-bar", "data-star-slot": ""}, h("div", {class: "spot-head"}, spot ? h("h3", {class: "group-title"}, "Radio") : null, h("span", {class: "spacer"}), part.gear, part.clear), part.box);
    radioParts.bars.push(part);
    return part;
  }

  function drawBars() {
    for (const part of liveParts("bars")) {
      part.clear.disabled = !state.silence;
    }
  }

  function cardHead(title, ...tools) {
    return h("div", {class: "radio-card-head", "data-star-slot": ""}, h("h3", {class: "group-title"}, title), tools);
  }

  function stationFold(part) {
    part.stations = h("ul", {class: "stations", "aria-label": "Stations"});
    part.now = h("span", {class: "station-now-box"});
    return h("details", {class: "radio-station", on: {toggle: (event) => placeStation(event.currentTarget)}},
      h("summary", {title: "Internet radio: the stations, their schedule and Play or Stop"}, caret(), h("h3", {class: "group-title"}, "Internet radio"), part.now),
      h("div", {class: "station-body"}, h("div", {class: "station-tools"}, btn("Edit stations", "btn small ghost", stationsSheet)), part.stations));
  }

  function placeStation(fold) {
    if (!fold.open) {
      return;
    }
    const edge = fold.getBoundingClientRect();
    let [top, bottom] = [0, window.innerHeight];
    for (let node = fold.parentElement; node && node !== document.documentElement; node = node.parentElement) {
      const look = getComputedStyle(node);
      if (look.overflowX !== "visible" || look.overflowY !== "visible") {
        const clip = node.getBoundingClientRect();
        [top, bottom] = [Math.max(top, clip.top), Math.min(bottom, clip.bottom)];
      }
    }
    const [above, below] = [Math.floor(edge.top - top), Math.floor(bottom - edge.bottom)];
    fold.style.removeProperty("--room");
    const up = above >= fold.querySelector(".station-body").offsetHeight || above >= below;
    fold.dataset.side = up ? "up" : "down";
    fold.style.setProperty("--room", `${Math.max(0, up ? above : below)}px`);
  }

  function placeStations(event) {
    for (const fold of document.querySelectorAll("details.radio-station[open]")) {
      if (!(event && event.target instanceof Node && fold.contains(event.target))) {
        placeStation(fold);
      }
    }
  }

  function deviceCard() {
    const part = {stationsSig: ""};
    const face = faceplate(part);
    part.root = h("section", {class: "radio-card radio-device", "data-panel": "radio-device", "aria-label": "Device"}, cardHead("Device"), face, stationFold(part));
    radioParts.devices.push(part);
    return part;
  }

  function speakCard() {
    const {form, recipient, text, channel} = composerForm();
    const part = {recipient, text, channel, names: ""};
    part.root = h("section", {class: "radio-card radio-speak", "data-panel": "radio-speak", "aria-label": "Speak"}, cardHead("Speak"), form);
    radioParts.speaks.push(part);
    return part;
  }

  function drawSpeak() {
    const names = agentNames();
    const sig = JSON.stringify(names);
    for (const part of liveParts("speaks")) {
      if (sig !== part.names) {
        part.names = sig;
        const chosen = part.recipient.value;
        part.recipient.replaceChildren(...names.map((name) => h("option", {value: name, selected: name === chosen}, name)), ...(chosen && !names.includes(chosen) ? [h("option", {value: chosen, selected: true}, chosen)] : []));
      }
    }
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
    const fallbacks = RadioSet.FALLBACKS.map((id) => chip(FALLBACK_LABELS[id][0], radioSet.fallback === id, FALLBACK_LABELS[id][1], () => {
      keepRadio({fallback: id});
      redrawFilters();
    }, false));
    return h("div", {class: "radio-read", "aria-label": "Read aloud"},
      h("p", {class: "muted"}, state.speech.tts ? "The radio sounds for these classes and agents, each speaker with its own voice; MAYDAY always sounds." : `The hub speaks no line: ${state.speech.tts_off}. The fallback and the procedure words stand in.`),
      h("div", {class: "chips", role: "group", "aria-label": "Classes"}, classes),
      agents.length ? h("div", {class: "chips", role: "group", "aria-label": "Agents"}, agents) : null,
      h("div", {class: "chips radio-fallback", role: "group", "aria-label": "Fallback", title: "Fallback: what plays in Auto above the threshold and in Quiet, kept in this browser"}, h("span", {class: "chips-label"}, "Fallback"), fallbacks),
      morseSpeed());
  }

  function redrawFilters() {
    for (const part of liveParts("bars")) {
      if (!part.box.hidden) {
        part.box.replaceChildren(radioFilters());
      }
    }
  }

  function drawRadioSet() {
    for (const part of liveParts("devices")) {
      for (const button of part.face.modes.querySelectorAll("button[data-mode]")) {
        button.setAttribute("aria-pressed", String(button.dataset.mode === radioSet.mode));
      }
      const {tones, squelch, threshold} = part.knobs;
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
      drawGate(threshold, settings.speech.threshold);
    }
    drawDisplay();
    drawLog();
  }

  function drawRadio() {
    drawRadioSet();
    drawStations();
    drawSpeak();
    drawBars();
  }

  /**
   * @param {boolean} spot whether the body fills the radio spot rather than a Home tile.
   * @returns {object} its bar, device, speak and history parts and the grid holding the three cards.
   */
  function radioBody(spot) {
    const bar = radioBar(spot);
    const device = deviceCard();
    const speak = speakCard();
    const history = historyCard();
    window.setTimeout(drawRadio, 0);
    return {bar, device, speak, history, grid: h("div", {class: "radio-grid"}, device.root, h("div", {class: "radio-column"}, speak.root, history.root))};
  }

  /**
   * @param {string} id the Home panel id: radio, radio-device, radio-speak or radio-log.
   * @returns {Element} a second live instance of that part for a Home tile, without ids and without stars of its own.
   */
  function radioPart(id) {
    const body = id === "radio" ? radioBody(false) : null;
    const made = body ? [body.bar.root, body.grid] : {"radio-device": deviceCard, "radio-speak": speakCard, "radio-log": historyCard}[id]().root;
    const root = h("div", {class: `radio-home radio-home-${id}`}, made);
    root.querySelectorAll("[data-panel]").forEach((node) => node.removeAttribute("data-panel"));
    root.querySelectorAll("[data-star-slot]").forEach((node) => node.removeAttribute("data-star-slot"));
    window.setTimeout(drawRadio, 0);
    return root;
  }
