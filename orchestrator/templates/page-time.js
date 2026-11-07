  function windowQuery() {
    if (ui.preset === -1) {
      return `from=${Math.floor(ui.from)}&to=${Math.ceil(ui.to)}`;
    }
    const end = ui.asOf === null ? nowSeconds() : ui.asOf;
    const begin = ui.preset === 0 ? 0 : end - ui.preset;
    return `from=${Math.floor(begin)}${ui.asOf === null ? "" : `&to=${Math.ceil(end)}`}`;
  }

  const localInput = (ts) => {
    const date = stampOf(ts);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  };

  function customRange() {
    const from = h("input", {type: "datetime-local", "aria-label": "Von", value: localInput(ui.from === null ? state.since : ui.from)});
    const to = h("input", {type: "datetime-local", "aria-label": "Bis", value: localInput(ui.to === null ? state.until : ui.to)});
    return h("span", {class: "custom"}, from, h("span", {class: "muted"}, "bis"), to,
      h("button", {type: "button", class: "btn small soft", on: {click: () => {
        const begin = Date.parse(from.value) / 1000;
        const end = Date.parse(to.value) / 1000;
        if (!Number.isFinite(begin) || !Number.isFinite(end) || begin >= end) {
          toast("Zeitraum ungültig", ["„Von“ muss vor „Bis“ liegen."], false);
          return;
        }
        stopReplay();
        ui.preset = -1;
        ui.from = begin;
        ui.to = end;
        reload();
      }}}, "Anwenden"));
  }

  function timeBar() {
    const bar = document.getElementById("time");
    const presets = h("div", {class: "segmented", role: "group", "aria-label": "Zeitraum"});
    const summary = h("summary", {title: "Zeitraum und Wiedergabe"});
    const slider = h("input", {type: "range", min: 0, max: 1000, step: 1, value: 1000, "aria-label": "Stand der Wiedergabe"});
    const play = iconBtn("bi-play-fill", "Wiedergabe", "btn small soft", null);
    const liveButton = h("button", {type: "button", class: "btn small ghost"}, "Live");
    const label = h("span", {class: "window-label"});
    for (const [seconds, name] of PRESETS.filter(([seconds]) => seconds !== -1)) {
      presets.append(h("button", {type: "button", "data-preset": seconds, on: {click: () => choosePreset(seconds)}}, name));
    }
    slider.addEventListener("input", () => {
      stopReplay();
      const span = state.now - state.first;
      ui.asOf = Number(slider.value) >= 1000 ? null : state.first + (span * Number(slider.value)) / 1000;
      reload();
    });
    play.addEventListener("click", () => (ui.playing ? stopReplay() : startReplay()));
    liveButton.addEventListener("click", () => {
      stopReplay();
      ui.asOf = null;
      if (ui.preset === -1) {
        ui.preset = DAY;
      }
      reload();
    });
    bar.append(summary, h("div", {class: "menu-box end"}, h("h3", {}, "Zeitraum"), presets, h("h3", {}, "Wiedergabe"), h("div", {class: "replay"}, play, slider, liveButton), label,
      h("p", {class: "muted"}, "Einen eigenen Zeitraum setzt Filter ▾ im Stream.")));
    timeDom = {summary, presets, slider, play, live: liveButton, label};
  }

  function reload() {
    load();
    if (ui.screen === "stream") {
      fetchEvents();
    }
  }

  function choosePreset(seconds) {
    stopReplay();
    ui.preset = seconds;
    reload();
  }

  function drawTime() {
    if (!timeDom) {
      return;
    }
    for (const button of timeDom.presets.children) {
      button.setAttribute("aria-pressed", String(Number(button.dataset.preset) === ui.preset));
    }
    timeDom.summary.textContent = `${(PRESETS.find(([seconds]) => seconds === ui.preset) || [0, "eigener"])[1]}${ui.asOf === null ? "" : " · Wiedergabe"} ▾`;
    timeDom.slider.disabled = ui.preset === -1;
    timeDom.play.disabled = ui.preset === -1;
    timeDom.live.disabled = live();
    const span = Math.max(state.now - state.first, 1);
    if (!ui.playing) {
      timeDom.slider.value = String(ui.asOf === null ? 1000 : Math.round((1000 * (ui.asOf - state.first)) / span));
    }
    timeDom.label.textContent = `${absolute.format(stampOf(state.since))} – ${absolute.format(stampOf(state.until))}${live() ? " · live" : ""}`;
  }

  function startReplay() {
    if (ui.preset === -1) {
      return;
    }
    const began = state.first;
    const span = Math.max(state.now - began, 1);
    const resume = ui.asOf !== null && ui.asOf < state.now - 60;
    let progress = resume ? (ui.asOf - began) / span : 0;
    ui.playing = true;
    relabel(timeDom.play, "bi-pause-fill", "Pause");
    const advance = async () => {
      if (!ui.playing) {
        return;
      }
      progress = Math.min(progress + 1 / 48, 1);
      ui.asOf = progress >= 1 ? null : began + span * progress;
      timeDom.slider.value = String(Math.round(progress * 1000));
      await load();
      if (ui.screen === "stream") {
        fetchEvents();
      }
      if (progress >= 1) {
        stopReplay();
      } else if (ui.playing) {
        replay = window.setTimeout(advance, 500);
      }
    };
    advance();
  }

  function stopReplay() {
    ui.playing = false;
    window.clearTimeout(replay);
    if (timeDom) {
      relabel(timeDom.play, "bi-play-fill", "Wiedergabe");
    }
  }
