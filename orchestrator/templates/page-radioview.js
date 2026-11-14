  const STATION_TONES = {playing: "ok", loading: "info", reload: "info", blocked: "warn", error: "bad", due: "teal", stopped: "neutral", idle: "neutral", off: "neutral"};
  const NOTE_ID = /^[0-9a-f]{16}$/;
  const MODE_LABELS = {
    auto: ["bi-volume-up", "Auto", "Auto: speech while the host CPU lies below the threshold, otherwise the noise burst"],
    quiet: ["bi-soundwave", "Quiet", "Quiet: the noise burst only, never speech; MAYDAY, PAN-PAN and Sécurité still sound their procedure word"],
    silence: ["bi-volume-mute", "Silence", "Silence: no sound, bubbles and log only; MAYDAY, PAN-PAN and Sécurité still sound their procedure word"],
  };
  const TAB_LABELS = {sent: ["bi-arrow-up-right", "Sent", "Sent: what you transmitted"], received: ["bi-arrow-down-left", "Received", "Received: radio to you or to all"], all: ["bi-journal-text", "All", "All: every radio row the hub logs"]};
  const CHIP_LABELS = {class: "Class", from: "Sender", to: "Recipient", agent: "Agent"};
  const COPIED = 1600;
  const FOLDED_READERS = 3;
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
      cpu.title = gate.cpu === null
        ? `No host CPU sample of the last two minutes: the hub renders no new speech line, threshold ${gate.threshold} %`
        : `Host CPU ${fixed(gate.cpu)} %: new speech renders below ${gate.threshold} %${gate.open ? "" : ", so the radio plays the burst"}`;
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
    return {input, value, row: h("div", {class: "knob-row", title: hint}, h("span", {class: "knob-label", title: label}, label), input, value)};
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
    return h("div", {class: "radio-read", "aria-label": "Read aloud"},
      h("p", {class: "muted"}, state.speech.tts ? "The radio sounds for these classes and agents, each speaker with its own voice; MAYDAY always sounds." : `The hub speaks no line: ${state.speech.tts_off}. The burst and the procedure words stand in.`),
      h("div", {class: "chips", role: "group", "aria-label": "Classes"}, classes),
      agents.length ? h("div", {class: "chips", role: "group", "aria-label": "Agents"}, agents) : null);
  }

  function redrawFilters() {
    for (const part of liveParts("bars")) {
      if (!part.box.hidden) {
        part.box.replaceChildren(radioFilters());
      }
    }
  }

  function keepLog(change) {
    keepRadio({log: {...radioSet.log, ...change}});
  }

  function chipSelect(name) {
    const label = CHIP_LABELS[name];
    const select = h("select", {class: "field", "aria-label": label, title: `${label}: filter the log`, on: {change: (event) => keepLog({chips: {...radioSet.log.chips, [name]: event.target.value}})}});
    return h("label", {class: "chip-select", "data-chip": name, "data-active": "false"}, select);
  }

  function fillChip(chip, values) {
    const name = chip.dataset.chip;
    const chosen = radioSet.log.chips[name];
    const options = [...new Set([...values, ...(chosen ? [chosen] : [])])];
    const select = chip.querySelector("select");
    const sig = JSON.stringify([options, chosen || ""]);
    if (select.sig !== sig) {
      select.sig = sig;
      select.replaceChildren(h("option", {value: ""}, `${CHIP_LABELS[name]}: any`), ...options.map((value) => h("option", {value, selected: value === chosen}, name === "class" ? CLASSES[value] || value : value)));
    }
    setAttr(chip, "data-active", String(Boolean(chosen)));
  }

  function setAttr(node, name, value) {
    if (node.getAttribute(name) !== value) {
      node.setAttribute(name, value);
    }
  }

  function setText(node, value) {
    if (node.textContent !== value) {
      node.textContent = value;
    }
  }

  function firstLine(text) {
    return text.split("\n").map((part) => part.trim()).find(Boolean) || "";
  }

  function logLine(row) {
    const message = row.sent ? row : RadioSet.ledgerOf(row, state.messages);
    const sent = Boolean(message);
    const [name, label] = sent ? ["bi-arrow-up-right", "Sent"] : ["bi-arrow-down-left", "Received"];
    const first = firstLine(row.text);
    const line = h("li", {class: "radio-row", "data-key": row.key, "data-dir": sent ? "sent" : "received", "data-class": row.class, "data-ts": row.ts, on: {click: (event) => openRadioRow(event.currentTarget.row, event.currentTarget)}},
      h("button", {type: "button", class: "radio-pick", "aria-haspopup": "dialog", title: first},
        when(row.ts),
        h("span", {class: "radio-dir", role: "img", ...named(label)}, icon(name)),
        klass(row.class),
        h("span", {class: "radio-route"}, `${row.from} → ${targetsOf(row)}`),
        h("span", {class: "radio-line"}, first)),
      foldedReaders(row));
    line.row = row;
    return line;
  }

  function keepLine(kept, fresh) {
    kept.row = fresh.row;
    if (kept.outerHTML === fresh.outerHTML) {
      return kept;
    }
    for (const name of ["data-dir", "data-class"]) {
      setAttr(kept, name, fresh.getAttribute(name));
    }
    const [pick, twin] = [kept.querySelector(".radio-pick"), fresh.querySelector(".radio-pick")];
    setAttr(pick, "title", twin.getAttribute("title"));
    pick.replaceChildren(...twin.childNodes);
    for (const node of [...kept.children].filter((child) => child !== pick)) {
      node.remove();
    }
    kept.append(...[...fresh.children].filter((child) => child !== twin));
    return kept;
  }

  function patchList(list, lines) {
    const before = [...list.children];
    const focused = before.find((node) => node.contains(document.activeElement)) || null;
    const old = new Map(before.filter((node) => node.dataset.key).map((node) => [node.dataset.key, node]));
    const wanted = lines.map((line) => {
      const kept = old.get(line.dataset.key);
      old.delete(line.dataset.key);
      return kept ? keepLine(kept, line) : line;
    });
    const keep = new Set(wanted);
    for (const node of before.filter((child) => !keep.has(child))) {
      node.remove();
    }
    wanted.forEach((node, index) => {
      if (list.children[index] !== node) {
        list.insertBefore(node, list.children[index] || null);
      }
    });
    if (focused && !focused.isConnected) {
      const at = before.indexOf(focused);
      const near = before.filter((node) => node.isConnected && node.querySelector(".radio-pick")).sort((a, b) => Math.abs(before.indexOf(a) - at) - Math.abs(before.indexOf(b) - at))[0];
      (near ? near.querySelector(".radio-pick") : list).focus({preventScroll: true});
    }
  }

  function foldedReaders(row) {
    const strip = readerRow(row);
    const {shown, hidden} = Receipts.strip(row);
    const rest = shown.length + hidden.length - FOLDED_READERS;
    if (strip && rest > 0) {
      strip.append(h("span", {class: "readers-more readers-fold", role: "img", ...named(`${rest} more readers`, [...shown, ...hidden].slice(FOLDED_READERS).map(readLabel).join("\n"))}, `+${rest}`));
    }
    return strip;
  }

  function readerLine(reader) {
    const known = reader.read !== null && reader.read !== undefined;
    return h("li", {class: "popup-reader", "data-session": reader.session, "data-acked": String(reader.acked)},
      face(people()[reader.session] ? reader.session : reader.name, false),
      h("strong", {}, reader.name),
      h("span", {class: "muted"}, known ? `read ${reader.approximate ? "about " : ""}${absolute.format(stampOf(reader.read))}` : "read, time unknown"),
      reader.acked ? pill("acknowledged", "ok") : null);
  }

  function copyText(text) {
    const said = h("span", {class: "radio-said", role: "status", "aria-live": "polite"});
    const button = h("button", {type: "button", class: "btn small radio-copy", ...named("Copy", "Copy: the full message to the clipboard")}, icon("bi-clipboard"), h("span", {}, "Copy"));
    const show = (name, word, done, note) => {
      button.replaceChildren(icon(name), h("span", {}, word));
      button.setAttribute("aria-label", word);
      button.dataset.copied = done;
      said.textContent = note;
    };
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        show("bi-clipboard-check", "Copied", "true", "Copied: the full message is on the clipboard");
      } catch {
        show("bi-x-circle", "Not copied", "false", "Not copied: the browser refused the clipboard");
      }
      window.setTimeout(() => show("bi-clipboard", "Copy", "", ""), COPIED);
    });
    return [button, said];
  }

  function replyTarget(list) {
    const home = list ? list.closest(".radio-home") : null;
    if (!home) {
      return spotDom.speak;
    }
    const homes = liveParts("speaks").filter((part) => part.root.closest(".radio-home"));
    return homes.find((part) => home.contains(part.root)) || homes.find((part) => part.root.closest(".radio-home-radio-speak")) || homes[0] || spotDom.speak;
  }

  function replyTo(row, list) {
    const who = row.from === HUMAN && row.to.length ? row.to[0] : row.from;
    const part = replyTarget(list);
    closePopup();
    if (part === spotDom.speak) {
      openSpot(true);
    }
    part.channel.value = "post";
    part.channel.dispatchEvent(new Event("change", {bubbles: true}));
    if (![...part.recipient.options].some((option) => option.value === who)) {
      part.recipient.append(h("option", {value: who}, who));
    }
    part.recipient.value = who;
    part.text.focus();
  }

  function openRadioRow(row, li) {
    const message = row.sent ? row : RadioSet.ledgerOf(row, state.messages);
    const {shown, hidden} = Receipts.strip(row);
    const readers = [...shown, ...hidden];
    const list = li.closest("ul");
    const anchor = () => (list ? [...list.querySelectorAll(".radio-row")].find((item) => item.dataset.key === row.key) || null : null);
    openPopup(`Radio message from ${row.from}`, [
      popupHead(klass(row.class), `${row.from} → ${targetsOf(row)}`),
      meta([["Sender", row.from], ["Recipient", targetsOf(row)], ["Class", CLASSES[row.class] || row.class], ["Time", absolute.format(stampOf(row.ts))]]),
      h("pre", {class: "radio-full"}, row.text),
      voiceReplay(message ? message.voice : null),
      h("div", {class: "actions radio-actions"},
        h("button", {type: "button", class: "btn small primary radio-reply", ...named("Reply", "Reply: a post to the sender in the speak card"), on: {click: () => replyTo(row, list)}}, icon("bi-reply"), "Reply"),
        copyText(row.text)),
      h("h3", {}, readers.length ? `Read by ${readers.length}` : "Read by nobody yet"),
      readers.length ? h("ul", {class: "popup-readers"}, readers.map(readerLine)) : null,
    ].filter(Boolean), anchor);
  }

  function drawLog() {
    const entry = radioSet.log;
    const sig = JSON.stringify([state.radio.length, state.radio.length ? state.radio[state.radio.length - 1].ts : 0, state.messages.length, Receipts.signature(state.radio), Receipts.signature(state.messages), entry, Math.floor(Date.now() / 60000)]);
    for (const dom of liveParts("logs")) {
      if (sig !== dom.sig) {
        dom.sig = sig;
        drawLogPart(dom, entry);
      }
    }
  }

  function drawLogPart(dom, entry) {
    const counts = RadioSet.counts(state.radio, HUMAN, state.messages);
    for (const button of dom.tabs.children) {
      const {tab} = button.dataset;
      const count = button.querySelector(".count");
      setAttr(button, "aria-selected", String(tab === entry.tab));
      setAttr(count, "aria-label", `${counts[tab]} rows`);
      setText(count, String(counts[tab]));
    }
    const choices = RadioSet.choices(state.radio);
    for (const chip of dom.chips.children) {
      fillChip(chip, choices[chip.dataset.chip]);
    }
    if (document.activeElement !== dom.search && dom.search.value !== entry.q) {
      dom.search.value = entry.q;
    }
    const rows = RadioSet.logRows(state.radio, entry, HUMAN, state.messages);
    patchList(dom.list, rows.length ? rows.map(logLine) : [h("li", {class: "muted"}, state.radio.length ? "No radio row matches the tab, the chips and the search." : "No radio in the chosen time range yet.")]);
  }

  function historyCard() {
    const tabs = h("div", {class: "radio-tabs", role: "tablist", "aria-label": "Log"}, RadioSet.TABS.map((tab) => {
      const [name, label, hint] = TAB_LABELS[tab];
      return h("button", {type: "button", role: "tab", "data-tab": tab, "aria-selected": "false", title: hint, on: {click: () => keepLog({tab})}}, icon(name), label, h("span", {class: "count"}));
    }));
    const chips = h("div", {class: "radio-chips", role: "group", "aria-label": "Log filters"}, RadioSet.CHIPS.map(chipSelect));
    const search = h("input", {type: "search", class: "field", placeholder: "Search the log …", maxlength: 200, ...named("Search the log"), on: {input: (event) => keepLog({q: event.target.value})}});
    const clear = iconBtn("bi-x-circle", "Clear filters", "btn small ghost", () => keepRadio({log: RadioSet.cleared(radioSet.log)}), "Clear filters: every chip and the search");
    const list = h("ul", {class: "radio-log", tabindex: "-1", "aria-label": "Radio log"});
    const part = {tabs, chips, search, list, sig: ""};
    part.root = h("section", {class: "radio-card radio-logbox", "data-panel": "radio-log", "aria-label": "Radio log"}, cardHead("History", tabs, search), h("div", {class: "radio-filters"}, chips, clear), list);
    radioParts.logs.push(part);
    return part;
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
      threshold.value.textContent = `${settings.speech.threshold} %`;
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
