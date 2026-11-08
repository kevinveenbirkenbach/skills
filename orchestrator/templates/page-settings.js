  let redirectsTold = "";

  function adoptSettings(next) {
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
    musicButton();
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
    const tones = SOUND_KINDS.map(([id, label]) => {
      const on = h("input", {type: "checkbox", checked: settings.sounds[id].on, "aria-label": `${label} on`});
      const level = h("input", {type: "range", min: 0, max: 1, step: 0.05, value: settings.sounds[id].volume, "aria-label": `${label} volume`});
      const loudest = () => Math.max(...tones.map((tone) => Number(tone.level.value)), Number(volume.value));
      return {id, on, level, row: h("div", {class: "sound-row"}, h("strong", {}, label), h("label", {class: "check"}, on, "on"), level, btn("Test", "btn small ghost", () => play(id, id === "mayday" ? loudest() : Number(level.value))))};
    });
    const squelch = h("input", {type: "range", min: 0, max: 1, step: 0.05, value: settings.squelch, "aria-label": "Squelch"});
    const notify = h("input", {type: "checkbox", checked: settings.notify});
    const speechOn = h("input", {type: "checkbox", checked: settings.speech.on, disabled: !state.speech.tts});
    const spoken = SPEECH_CLASSES.map(([id, label]) => ({id, label, box: h("input", {type: "checkbox", checked: id === "mayday" || settings.speech.classes.includes(id), disabled: id === "mayday", title: id === "mayday" ? "MAYDAY is always read aloud" : null})}));
    const stations = Object.entries(people()).sort(([, a], [, b]) => a.now.localeCompare(b.now))
      .map(([key, entry]) => ({key, label: entry.now, box: h("input", {type: "checkbox", checked: !settings.speech.muted.includes(key), "aria-label": `Read ${entry.now} aloud`})}));
    const absent = settings.speech.muted.filter((key) => !people()[key]);
    const sample = btn("Test", "btn small ghost", () => say({text: state.speech.sample, voice: state.speech.operator, tone: "direct", cls: "newsletter", who: HUMAN, line: "radio check"}));
    sample.disabled = !state.speech.tts;
    const list = h("div", {class: "mini"});
    const rows = [];
    settings.streams.forEach((stream) => streamRow(stream, rows, list));
    const form = h("form", {class: "settings"},
      ambience(),
      h("section", {}, h("h3", {}, "Location"), h("p", {class: "muted"}, "Sun, moon and stars stand where you see them from here, looking south; under 🔭 Sky (key h) you turn the view. Decimal degrees, north and east positive."),
        h("div", {class: "grid"}, h("label", {}, "Latitude", latitude), h("label", {}, "Longitude", longitude))),
      h("section", {}, h("h3", {}, "Appearance"), h("label", {}, "Colors", theme), custom, verdict),
      h("section", {}, h("h3", {}, "Music"), h("p", {class: "muted"}, "Generative ambient music, made offline: calm with an empty inbox, a little tenser when something waits, quieter under messages."),
        h("div", {class: "grid"}, h("label", {class: "check"}, musicOn, "Music on"), h("label", {}, "Overall volume (music and radio)", volume))),
      h("section", {}, h("h3", {}, "Tones and notifications"), h("p", {class: "muted"}, "MAYDAY and PAN-PAN are always loudest. With several new events only the most urgent one plays."),
        tones.map((tone) => tone.row), h("label", {}, "Squelch: scales every tone, 0 plays none", squelch), h("label", {class: "check"}, notify, "Show desktop notifications when the browser allows them")),
      h("section", {}, h("h3", {}, "Read radio aloud"),
        h("p", {class: "muted"}, state.speech.tts
          ? "New radio is read aloud in maritime radio style (SMCP), one message after another, each speaker with its own voice; music and internet radio go quieter meanwhile. The volume follows the tones above; MAYDAY is always spoken, and loudest."
          : `The radio stays silent: ${state.speech.tts_off}.`),
        h("div", {class: "days"}, h("label", {class: "check"}, speechOn, "Read radio aloud"), sample),
        h("div", {class: "days", role: "group", "aria-label": "Classes"}, spoken.map((entry) => h("label", {class: "check"}, entry.box, entry.label))),
        stations.length ? h("div", {class: "days", role: "group", "aria-label": "Speakers"}, stations.map((entry) => h("label", {class: "check"}, entry.box, entry.label))) : null),
      h("section", {}, h("h3", {}, "Internet radio"), h("p", {class: "muted"}, "Internet radio at fixed times with a 3 s fade in and out; the music pauses meanwhile. A new station plays around the clock until you change its times; under Stream → Radio you start and stop it by hand. The page may load sound only from these addresses; your passkey signs a new address. If a signed station redirects, the server resolves the redirect when you save a new station or a changed address and releases its target; the note after saving names it."),
        list, h("div", {}, btn("+ Station", "btn small soft", () => streamRow({name: "", url: "", from: "00:00", to: "24:00", days: [0, 1, 2, 3, 4, 5, 6], on: true, via: []}, rows, list)))),
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
        sounds: Object.fromEntries(tones.map((tone) => [tone.id, {on: tone.on.checked, volume: Number(tone.level.value)}])),
        squelch: Number(squelch.value),
        notify: notify.checked,
        streams: rows.map((entry) => entry.read()),
        speech: {
          on: speechOn.checked,
          classes: spoken.filter((entry) => entry.box.checked).map((entry) => entry.id),
          muted: [...absent, ...stations.filter((entry) => !entry.box.checked).map((entry) => entry.key)],
        },
        space: savedSpace(),
      };
      if (await saveSettings(next)) {
        closeSheet();
        toast("Settings saved", [], true);
      }
    });
    openSheet("Settings and ambience", [form], false);
  }
