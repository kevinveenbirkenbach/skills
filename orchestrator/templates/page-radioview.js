  const STATION_TONES = {playing: "ok", loading: "info", reload: "info", blocked: "warn", error: "bad", due: "teal", stopped: "neutral", idle: "neutral", off: "neutral"};
  const NOTE_ID = /^[0-9a-f]{16}$/;
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
      return ["off", "off", "Switched off in the settings"];
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
      : [h("li", {class: "muted"}, "No station yet: add one under ⚙ Settings → Internet radio.")]));
  }

  function speakerChips() {
    return Object.entries(people()).sort(([, a], [, b]) => a.now.localeCompare(b.now)).map(([key, entry]) => h("li", {class: "speaker", "data-key": key, title: entry.now},
      h("span", {class: "speaker-face"}, face(key, false)), h("span", {class: "speaker-name"}, entry.now)));
  }

  function drawSpeaker() {
    const now = speech.current && speech.current.who ? speech.current : null;
    for (const art of document.querySelectorAll(".avatar[data-face]")) {
      art.classList.toggle("speaking", Boolean(now && art.dataset.face === now.who));
    }
    if (radioDom) {
      for (const chip of radioDom.speakers.querySelectorAll(".speaker")) {
        chip.classList.toggle("speaking", Boolean(now && chip.dataset.key === now.who));
      }
      radioDom.caption.hidden = !now;
      radioDom.caption.replaceChildren(...(now ? [
        h("span", {class: "speaker-face"}, face(now.who, false)),
        h("strong", {}, `${nameOf(now.who)} speaking`),
        h("span", {class: "caption-line", title: now.line}, now.line),
        iconBtn("bi-stop-fill", "Stop speaking", "btn small ghost", cancelSpeech),
      ] : []));
    }
    if (ui.screen === "agents" && (ui.views.agents === "orbit" || ui.views.agents === "chord")) {
      stage();
    }
  }

  function sentRows() {
    const rows = state.messages.slice(-5).reverse();
    return rows.length ? h("ul", {class: "mini"}, rows.map((message) => h("li", {},
      h("div", {class: "row"}, klass(message.class || "post"), when(message.created_ts)),
      h("span", {class: "muted"}, `to ${message.to === "*" ? "all" : message.to}`),
      h("span", {}, short(message.text)),
      voiceReplay(message.voice)))) : h("p", {class: "muted"}, "Nothing sent in the chosen time range yet.");
  }

  function drawRadio() {
    if (!radioDom) {
      return;
    }
    const crew = JSON.stringify(people());
    if (crew !== radioDom.crew) {
      radioDom.crew = crew;
      radioDom.speakers.replaceChildren(...speakerChips());
      drawSpeaker();
    }
    const names = agentNames();
    if (JSON.stringify(names) !== radioDom.names) {
      radioDom.names = JSON.stringify(names);
      const chosen = radioDom.recipient.value;
      radioDom.recipient.replaceChildren(...names.map((name) => h("option", {value: name, selected: name === chosen}, name)));
    }
    const sent = JSON.stringify(state.messages.slice(-5));
    if (sent !== radioDom.sent) {
      radioDom.sent = sent;
      radioDom.outbox.replaceChildren(sentRows());
    }
    drawStations();
  }

  function radioScreen() {
    const speakers = h("ul", {class: "speakers", "aria-label": "Speakers"});
    const caption = h("div", {class: "radio-caption", role: "status", "aria-live": "polite", hidden: true});
    const stations = h("ul", {class: "stations", "aria-label": "Stations"});
    const outbox = h("div", {});
    const {form, recipient} = composerForm();
    radioDom = {speakers, caption, stations, outbox, recipient, crew: "", names: "", sent: "", stationsSig: ""};
    return h("div", {class: "stack radio-view"},
      h("h2", {class: "title"}, "Radio"),
      h("div", {class: "radio-grid"},
        h("section", {class: "card radio-talk", "aria-label": "Radio"}, h("h3", {class: "group-title"}, "Radio"), caption, speakers, form),
        h("div", {class: "stack"},
          h("section", {class: "card", "aria-label": "Internet radio"},
            h("div", {class: "card-head"}, h("h3", {class: "group-title"}, "Internet radio"), btn("Edit stations", "btn small ghost", settingsSheet)),
            stations),
          h("section", {class: "card", "aria-label": "Recently sent"}, h("h3", {class: "group-title"}, "Recently sent"), outbox))));
  }
