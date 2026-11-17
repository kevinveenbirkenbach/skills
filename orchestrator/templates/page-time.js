  const SPAN_STEPS = 1000;
  const SHORTEST = 60;

  function windowQuery() {
    const end = ui.asOf === null ? nowSeconds() : ui.asOf;
    const begin = ui.preset === 0 ? 0 : end - ui.preset;
    return `from=${Math.floor(begin)}${ui.asOf === null ? "" : `&to=${Math.ceil(end)}`}`;
  }

  const localInput = (ts) => {
    const date = stampOf(ts);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  };

  function spanName(seconds) {
    if (seconds >= DAY) {
      return `${Math.round(seconds / DAY)} d`;
    }
    return seconds >= 3600 ? `${Math.round(seconds / 3600)} h` : `${Math.max(Math.round(seconds / 60), 1)} min`;
  }

  function windowName() {
    const preset = PRESETS.find(([seconds]) => seconds === ui.preset);
    return `${preset ? preset[1] : spanName(ui.preset)}${ui.asOf === null ? "" : " · past"}`;
  }

  /**
   * @param {number} begin the window's start in epoch seconds.
   * @param {number} end its end; at or after now the window is live and keeps its length.
   */
  function setWindow(begin, end) {
    stopReplay();
    const now = nowSeconds();
    const stop = Math.min(end, now);
    ui.preset = Math.max(Math.round(stop - begin), SHORTEST);
    ui.asOf = end >= now ? null : stop;
    reload();
  }

  function customRange() {
    const from = h("input", {type: "datetime-local", "aria-label": "From", value: localInput(state.since)});
    const to = h("input", {type: "datetime-local", "aria-label": "To", value: localInput(state.until)});
    return h("span", {class: "custom"}, from, h("span", {class: "muted"}, "to"), to,
      h("button", {type: "button", class: "btn small soft", on: {click: () => {
        const begin = Date.parse(from.value) / 1000;
        const end = Date.parse(to.value) / 1000;
        if (!Number.isFinite(begin) || !Number.isFinite(end) || begin >= end) {
          toast("Time range invalid", ["“From” must come before “To”."], false);
          return;
        }
        setWindow(begin, end);
      }}}, "Apply"));
  }

  function spanSlider() {
    const [from, to] = ["from", "to"].map((end, index) => h("input", {type: "range", class: `span-${end}`, min: 0, max: SPAN_STEPS, step: 1, value: index * SPAN_STEPS, "aria-label": `Time range ${end}`}));
    const fill = h("span", {class: "span-fill", "aria-hidden": "true"});
    const at = (value) => state.first + (Math.max(state.now - state.first, 1) * Number(value)) / SPAN_STEPS;
    const moved = (event) => {
      if (Number(from.value) >= Number(to.value)) {
        event.target.value = String(event.target === from ? Number(to.value) - 1 : Number(from.value) + 1);
      }
      setWindow(at(from.value), Number(to.value) >= SPAN_STEPS ? nowSeconds() : at(to.value));
    };
    from.addEventListener("input", moved);
    to.addEventListener("input", moved);
    return {box: h("div", {class: "span-slider"}, fill, from, to), from, to, fill};
  }

  function timeSection() {
    const presets = h("div", {class: "segmented", role: "group", "aria-label": "Time range"});
    for (const [seconds, name] of PRESETS) {
      presets.append(h("button", {type: "button", "data-preset": seconds, on: {click: () => choosePreset(seconds)}}, name));
    }
    const slider = spanSlider();
    const play = iconBtn("bi-play-fill", "Replay", "btn small soft", () => (ui.playing ? stopReplay() : startReplay()));
    const liveButton = h("button", {type: "button", class: "btn small ghost", on: {click: () => {
      stopReplay();
      ui.asOf = null;
      reload();
    }}}, "Live");
    const label = h("span", {class: "window-label"});
    timeDom = {presets, from: slider.from, to: slider.to, fill: slider.fill, play, live: liveButton, label};
    return [h("h3", {}, "Time range"), presets, slider.box, h("div", {class: "replay"}, play, liveButton, label), customRange()];
  }

  function reload() {
    load();
    fetchRates();
    if (ui.screen === "stream") {
      fetchEvents();
    }
  }

  function choosePreset(seconds) {
    stopReplay();
    ui.preset = seconds;
    ui.asOf = null;
    reload();
  }

  function drawTime() {
    if (!timeDom) {
      return;
    }
    for (const button of timeDom.presets.children) {
      button.setAttribute("aria-pressed", String(Number(button.dataset.preset) === ui.preset && ui.asOf === null));
    }
    const span = Math.max(state.now - state.first, 1);
    const end = ui.asOf === null ? state.now : ui.asOf;
    const place = (t) => Math.min(Math.max(Math.round((SPAN_STEPS * (t - state.first)) / span), 0), SPAN_STEPS);
    const [low, high] = [place(ui.preset === 0 ? state.first : end - ui.preset), ui.asOf === null ? SPAN_STEPS : place(end)];
    timeDom.from.value = String(Math.min(low, high - 1));
    timeDom.to.value = String(high);
    timeDom.from.classList.toggle("on-top", low > SPAN_STEPS / 2);
    timeDom.fill.style.left = `${(100 * low) / SPAN_STEPS}%`;
    timeDom.fill.style.right = `${100 - (100 * high) / SPAN_STEPS}%`;
    timeDom.live.disabled = live();
    timeDom.label.textContent = `${absolute.format(stampOf(state.since))} – ${absolute.format(stampOf(state.until))}${live() ? " · live" : ""}`;
  }

  function startReplay() {
    const began = state.first + (ui.preset === 0 ? 0 : ui.preset);
    const span = Math.max(state.now - began, 1);
    const resume = ui.asOf !== null && ui.asOf < state.now - 60;
    let progress = resume ? Math.max((ui.asOf - began) / span, 0) : 0;
    ui.playing = true;
    relabel(timeDom.play, "bi-pause-fill", "Pause");
    const advance = async () => {
      if (!ui.playing) {
        return;
      }
      progress = Math.min(progress + 1 / 48, 1);
      ui.asOf = progress >= 1 ? null : began + span * progress;
      await load();
      fetchRates();
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
      relabel(timeDom.play, "bi-play-fill", "Replay");
    }
  }
