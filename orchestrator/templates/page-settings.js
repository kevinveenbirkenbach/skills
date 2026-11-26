  let redirectsTold = "";

  function adoptSettings(next) {
    const before = settings.channels;
    settings = next;
    settingsSig = JSON.stringify(next);
    if (space.edits === space.saved) {
      space.views = {graph: {...next.space.graph}, sky: {...next.space.sky}};
      space.glides = {graph: null, sky: null};
      refresh3d();
    }
    sky.mode = "";
    drawSky();
    syncMusic();
    syncRadio();
    drawNotify();
    drawAgentSettings();
    drawLog();
    musicButton();
    syncBubbles();
    syncChannels(before);
    drawRates();
  }

  async function saveSettings(next) {
    const signed = await signedProof("/api/settings/sign", next, "Settings");
    if (!signed) {
      return false;
    }
    const result = await sendJson("/api/settings", {...next, proof: signed.proof});
    if (!result.ok || !result.data) {
      toast("Settings not saved", [`${result.status} ${result.text}`.trim()], false);
      return false;
    }
    const {settings: saved, problems} = result.data;
    const unresolved = problems.join("\n");
    if (unresolved && unresolved !== redirectsTold) {
      toast("Redirect not resolved", [...problems, "These stations load only from their own address for now; saving after ten minutes tries again."], false);
    }
    redirectsTold = unresolved;
    const fresh = [...new Set(saved.streams.flatMap((stream) => Ambience.stationOrigins(stream)))].filter((origin) => !pageMedia.has(origin));
    adoptSettings(saved);
    if (fresh.length) {
      toast("New station", ["The page reloads so the browser may play it. If the browser then blocks playback, a click starts the station.", `New for this page: ${fresh.join(", ")}`], true);
      window.setTimeout(() => window.location.reload(), 1500);
    }
    return true;
  }

  function streamRow(stream, rows, list) {
    const field = (attrs) => h("input", {class: "field", required: true, ...attrs});
    const name = field({type: "text", value: stream.name, placeholder: "Station name", maxlength: 120});
    const url = field({type: "url", value: stream.url, placeholder: "https://…"});
    const from = field({type: "time", value: stream.from});
    const to = field({type: "time", value: stream.to === "24:00" ? "00:00" : stream.to});
    const on = h("input", {type: "checkbox", checked: stream.on});
    const days = WEEKDAYS.map((label, index) => h("input", {type: "checkbox", checked: stream.days.includes(index), "aria-label": label}));
    const entry = {read: () => ({
      name: name.value.trim(),
      url: url.value.trim(),
      from: from.value,
      to: to.value === "00:00" && stream.to === "24:00" ? "24:00" : to.value,
      days: days.flatMap((box, index) => (box.checked ? [index] : [])),
      on: on.checked,
      via: stream.via,
    })};
    entry.row = h("div", {class: "stream-row"},
      h("div", {class: "grid"}, h("label", {}, "Name", name), h("label", {}, "Stream URL", url), h("label", {}, "from", from), h("label", {}, "to", to)),
      h("div", {class: "days"}, days.map((box, index) => h("label", {class: "check"}, box, WEEKDAYS[index])), h("label", {class: "check"}, on, "active"), h("span", {class: "spacer"}),
        btn("Remove", "btn small danger", () => {
          rows.splice(rows.indexOf(entry), 1);
          entry.row.remove();
        })));
    rows.push(entry);
    list.append(entry.row);
  }

  function ambience() {
    const tool = (id, name, label, title, run) => h("button", {type: "button", id, class: "btn small icon-only", ...named(label, title), on: {click: run}}, icon(name));
    const section = h("section", {}, h("h3", {}, "Ambience"), h("div", {class: "toolbar"},
      tool("sky-look", "bi-stars", "Sky", "Look at the sky: dragging turns the view (key h)", () => {
        closeSheet();
        skyLook(true);
      }),
      tool("music-toggle", "bi-music-note-beamed", "Music", "Music: generative music on or off", toggleMusic),
      tool("leitstand", "bi-display", "Control room", "Control room: full screen with large type", toggleLeitstand),
      tool("notify", "bi-bell", "Notifications", "Notifications: allow the browser's desktop notifications", askNotify)));
    window.setTimeout(() => {
      musicButton();
      notifyLabel();
    }, 0);
    return section;
  }

  function stationsSheet() {
    const list = h("div", {class: "mini"});
    const rows = [];
    settings.streams.forEach((stream) => streamRow(stream, rows, list));
    const form = h("form", {class: "settings", "aria-label": "Stations"},
      h("section", {}, h("h3", {}, "Internet radio"), h("p", {class: "muted"}, "Internet radio at fixed times with a 3 s fade in and out; the music pauses meanwhile. A new station plays around the clock until you change its times; in the radio panel you start and stop it by hand. The page may load sound only from these addresses; your passkey signs a new address. If a signed station redirects, the server resolves the redirect when you save a new station or a changed address and releases its target; the note after saving names it."),
        list, h("div", {}, btn("+ Station", "btn small soft", () => streamRow({name: "", url: "", from: "00:00", to: "24:00", days: [0, 1, 2, 3, 4, 5, 6], on: true, via: []}, rows, list)))),
      h("div", {class: "sheet-foot"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), h("button", {type: "submit", class: "btn primary"}, "Save")));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      context();
      if (await saveSettings({...settings, space: savedSpace(), streams: rows.map((entry) => entry.read())})) {
        closeSheet();
        toast("Stations saved", [], true);
      }
    });
    openSheet("Stations", [form], false);
  }

  function settingsSheet() {
    const number = (value, min, max, label) => h("input", {class: "field", type: "number", min, max, step: "any", value, required: true, "aria-label": label});
    const latitude = number(settings.latitude, -90, 90, "Latitude");
    const longitude = number(settings.longitude, -180, 180, "Longitude");
    const theme = h("select", {class: "field"}, THEME_CHOICES.map(([id, label]) => h("option", {value: id, selected: settings.theme === id}, label)));
    const colors = Object.fromEntries(COLOR_FIELDS.map(([id]) => [id, h("input", {type: "color", value: settings.colors[id]})]));
    const custom = h("div", {class: "grid"}, COLOR_FIELDS.map(([id, label]) => h("label", {}, label, colors[id])));
    const verdict = h("p", {class: "muted", "aria-live": "polite"});
    const judge = () => {
      custom.hidden = theme.value !== "custom";
      verdict.hidden = theme.value !== "custom";
      const panel = Ambience.THEMES[Ambience.modeOf(colors.top.value, colors.bottom.value)].panel;
      const ratio = Ambience.contrast(Ambience.hex(colors.accent.value), Ambience.hex(panel));
      verdict.textContent = `Accent on surfaces: contrast ${ratio.toFixed(1)} : 1${ratio < 3 ? "; too weak, pick a stronger accent" : ""}`;
    };
    theme.addEventListener("change", judge);
    Object.values(colors).forEach((input) => input.addEventListener("input", judge));
    judge();
    const musicOn = h("input", {type: "checkbox", checked: settings.music.on});
    const volume = h("input", {type: "range", min: 0, max: 1, step: 0.05, value: settings.music.volume, "aria-label": "Overall volume"});
    const undo = undoDial(settings.undo, "Undo window in seconds");
    const form = h("form", {class: "settings"},
      ambience(),
      h("section", {}, h("h3", {}, "Location"), h("p", {class: "muted"}, "Sun, moon and stars stand where you see them from here, looking south; under 🔭 Sky (key h) you turn the view. Decimal degrees, north and east positive."),
        h("div", {class: "grid"}, h("label", {}, "Latitude", latitude), h("label", {}, "Longitude", longitude))),
      h("section", {}, h("h3", {}, "Appearance"), h("label", {}, "Colors", theme), custom, verdict),
      h("section", {}, h("h3", {}, "Music"), h("p", {class: "muted"}, "Generative ambient music, made offline: calm with an empty inbox, a little tenser when something waits, quieter under messages."),
        h("div", {class: "grid"}, h("label", {class: "check"}, musicOn, "Music on"), h("label", {}, "Overall volume (music and radio)", volume))),
      h("section", {class: "undo-window"}, h("h3", {}, "Undo window"), h("p", {class: "muted"}, "Seconds between a passkey signature and the moment it takes effect, to undo it; 0 takes effect at once. Drag the hand, click a tick, or use the arrows (1 s) and Page Up / Down (5 s)."), undo.root),
      passkeySection(),
      h("div", {class: "sheet-foot"}, h("span", {class: "spacer"}), btn("Cancel", "btn ghost", closeSheet), h("button", {type: "submit", class: "btn primary"}, "Save")));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      context();
      const next = {
        latitude: Number(latitude.value),
        longitude: Number(longitude.value),
        theme: theme.value,
        colors: Object.fromEntries(COLOR_FIELDS.map(([id]) => [id, colors[id].value])),
        music: {on: musicOn.checked, volume: Number(volume.value)},
        channels: settings.channels,
        popups: settings.popups,
        agents: settings.agents,
        streams: settings.streams,
        speech: settings.speech,
        morse: settings.morse,
        space: savedSpace(),
        estimation: settings.estimation,
        trend: settings.trend,
        bubbles: settings.bubbles,
        rates: settings.rates,
        undo: undo.value(),
      };
      if (await saveSettings(next)) {
        closeSheet();
        toast("Settings saved", [], true);
      }
    });
    openSheet("Settings and ambience", [form], false);
  }
