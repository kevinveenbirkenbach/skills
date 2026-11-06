  function adoptSettings(next) {
    settings = next;
    settingsSig = JSON.stringify(next);
    if (space.edits === space.saved) {
      space.views = {graph: {...next.space.graph}, sky: {...next.space.sky}};
      space.glides = {graph: null, sky: null};
      requestSpace();
    }
    sky.mode = "";
    drawSky();
    syncMusic();
    syncRadio();
    musicButton();
  }

  async function saveSettings(next) {
    const result = await sendJson("/api/settings", next);
    if (!result.ok || !result.data) {
      toast("Einstellungen nicht gespeichert", [`${result.status} ${result.text}`.trim()], false);
      return false;
    }
    const fresh = result.data.streams.map((stream) => new URL(stream.url).origin).filter((origin) => !pageMedia.has(origin));
    adoptSettings(result.data);
    if (fresh.length) {
      toast("Neuer Sender", ["Die Seite lädt neu, damit der Browser ihn abspielen darf."], true);
      window.setTimeout(() => window.location.reload(), 1500);
    }
    return true;
  }

  function streamRow(stream, rows, list) {
    const field = (attrs) => h("input", {class: "field", required: true, ...attrs});
    const name = field({type: "text", value: stream.name, placeholder: "Sendername", maxlength: 120});
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
    })};
    entry.row = h("div", {class: "stream-row"},
      h("div", {class: "grid"}, h("label", {}, "Name", name), h("label", {}, "Stream-URL", url), h("label", {}, "von", from), h("label", {}, "bis", to)),
      h("div", {class: "days"}, days.map((box, index) => h("label", {class: "check"}, box, WEEKDAYS[index])), h("label", {class: "check"}, on, "aktiv"), h("span", {class: "spacer"}),
        btn("Entfernen", "btn small danger", () => {
          rows.splice(rows.indexOf(entry), 1);
          entry.row.remove();
        })));
    rows.push(entry);
    list.append(entry.row);
  }

  function ambience() {
    const tool = (id, label, title, run) => h("button", {type: "button", id, class: "btn small", title, on: {click: run}}, label);
    const section = h("section", {}, h("h3", {}, "Ambiente"), h("div", {class: "toolbar"},
      tool("sky-look", "🔭 Himmel", "Himmel ansehen: ziehen dreht den Blick (Taste h)", () => {
        closeSheet();
        skyLook(true);
      }),
      tool("music-toggle", "♪ Musik", "Generative Musik an oder aus", toggleMusic),
      tool("leitstand", "Leitstand", "Leitstand: Vollbild mit großer Schrift", toggleLeitstand),
      tool("notify", "Benachrichtigungen", "Desktop-Benachrichtigungen des Browsers erlauben", askNotify)));
    window.setTimeout(() => {
      musicButton();
      notifyLabel();
    }, 0);
    return section;
  }

  function settingsSheet() {
    const number = (value, min, max, label) => h("input", {class: "field", type: "number", min, max, step: "any", value, required: true, "aria-label": label});
    const latitude = number(settings.latitude, -90, 90, "Breite");
    const longitude = number(settings.longitude, -180, 180, "Länge");
    const theme = h("select", {class: "field"}, THEME_CHOICES.map(([id, label]) => h("option", {value: id, selected: settings.theme === id}, label)));
    const colors = Object.fromEntries(COLOR_FIELDS.map(([id]) => [id, h("input", {type: "color", value: settings.colors[id]})]));
    const custom = h("div", {class: "grid"}, COLOR_FIELDS.map(([id, label]) => h("label", {}, label, colors[id])));
    const verdict = h("p", {class: "muted", "aria-live": "polite"});
    const judge = () => {
      custom.hidden = theme.value !== "custom";
      verdict.hidden = theme.value !== "custom";
      const panel = Ambience.THEMES[Ambience.modeOf(colors.top.value, colors.bottom.value)].panel;
      const ratio = Ambience.contrast(Ambience.hex(colors.accent.value), Ambience.hex(panel));
      verdict.textContent = `Akzent auf Flächen: Kontrast ${ratio.toFixed(1)} : 1${ratio < 3 ? " – zu schwach, wähle einen kräftigeren Akzent" : ""}`;
    };
    theme.addEventListener("change", judge);
    Object.values(colors).forEach((input) => input.addEventListener("input", judge));
    judge();
    const musicOn = h("input", {type: "checkbox", checked: settings.music.on});
    const volume = h("input", {type: "range", min: 0, max: 1, step: 0.05, value: settings.music.volume, "aria-label": "Gesamtlautstärke"});
    const tones = SOUND_KINDS.map(([id, label]) => {
      const on = h("input", {type: "checkbox", checked: settings.sounds[id].on, "aria-label": `${label} an`});
      const level = h("input", {type: "range", min: 0, max: 1, step: 0.05, value: settings.sounds[id].volume, "aria-label": `${label} Lautstärke`});
      const loudest = () => Math.max(...tones.map((tone) => Number(tone.level.value)), Number(volume.value));
      return {id, on, level, row: h("div", {class: "sound-row"}, h("strong", {}, label), h("label", {class: "check"}, on, "an"), level, btn("Test", "btn small ghost", () => play(id, id === "mayday" ? loudest() : Number(level.value))))};
    });
    const notify = h("input", {type: "checkbox", checked: settings.notify});
    const speechOn = h("input", {type: "checkbox", checked: settings.speech.on, disabled: !state.speech.tts});
    const spoken = SPEECH_CLASSES.map(([id, label]) => ({id, label, box: h("input", {type: "checkbox", checked: id === "mayday" || settings.speech.classes.includes(id), disabled: id === "mayday", title: id === "mayday" ? "MAYDAY wird immer vorgelesen" : null})}));
    const stations = Object.entries(people()).sort(([, a], [, b]) => a.now.localeCompare(b.now))
      .map(([key, entry]) => ({key, label: entry.now, box: h("input", {type: "checkbox", checked: !settings.speech.muted.includes(key), "aria-label": `${entry.now} vorlesen`})}));
    const absent = settings.speech.muted.filter((key) => !people()[key]);
    const sample = btn("Test", "btn small ghost", () => say({text: state.speech.sample, voice: state.speech.operator, tone: "direct", cls: "newsletter"}));
    sample.disabled = !state.speech.tts;
    const list = h("div", {class: "mini"});
    const rows = [];
    settings.streams.forEach((stream) => streamRow(stream, rows, list));
    const form = h("form", {class: "settings"},
      ambience(),
      h("section", {}, h("h3", {}, "Ort"), h("p", {class: "muted"}, "Sonne, Mond und Sterne stehen dort, wo du sie von hier aus siehst, Blick nach Süden; unter 🔭 Himmel (Taste h) drehst du den Blick. Dezimalgrad, Nord und Ost positiv."),
        h("div", {class: "grid"}, h("label", {}, "Breite", latitude), h("label", {}, "Länge", longitude))),
      h("section", {}, h("h3", {}, "Darstellung"), h("label", {}, "Farben", theme), custom, verdict),
      h("section", {}, h("h3", {}, "Musik"), h("p", {class: "muted"}, "Generative Ambient-Musik, offline erzeugt: ruhig bei leerer Inbox, etwas gespannter, wenn etwas wartet, leiser unter Meldungen."),
        h("div", {class: "grid"}, h("label", {class: "check"}, musicOn, "Musik an"), h("label", {}, "Gesamtlautstärke (Musik und Radio)", volume))),
      h("section", {}, h("h3", {}, "Töne und Benachrichtigungen"), h("p", {class: "muted"}, "MAYDAY und PAN-PAN sind immer am lautesten. Bei mehreren neuen Ereignissen spielt nur das dringendste."),
        tones.map((tone) => tone.row), h("label", {class: "check"}, notify, "Desktop-Benachrichtigungen zeigen, wenn der Browser sie erlaubt")),
      h("section", {}, h("h3", {}, "Funk vorlesen"),
        h("p", {class: "muted"}, state.speech.tts
          ? "Neuer Funk wird in Seefunk-Sprechweise (SMCP) vorgelesen, eine Meldung nach der anderen, jede Station mit eigener Stimme; Musik und Radio werden solange leiser. Die Lautstärke folgt den Tönen oben, MAYDAY wird immer und am lautesten gesprochen."
          : `Der Funk bleibt stumm: ${state.speech.tts_off}.`),
        h("div", {class: "days"}, h("label", {class: "check"}, speechOn, "Funk vorlesen"), sample),
        h("div", {class: "days", role: "group", "aria-label": "Klassen"}, spoken.map((entry) => h("label", {class: "check"}, entry.box, entry.label))),
        stations.length ? h("div", {class: "days", role: "group", "aria-label": "Stationen"}, stations.map((entry) => h("label", {class: "check"}, entry.box, entry.label))) : null),
      h("section", {}, h("h3", {}, "Radio"), h("p", {class: "muted"}, "Internetradio zu festen Zeiten mit 3 s Ein- und Ausblenden; die Musik pausiert solange. Die Seite darf nur von diesen Adressen Ton laden."),
        list, h("div", {}, btn("+ Sender", "btn small soft", () => streamRow({name: "", url: "", from: "07:00", to: "09:00", days: [0, 1, 2, 3, 4], on: true}, rows, list)))),
      passkeySection(),
      h("div", {class: "sheet-foot"}, h("span", {class: "spacer"}), btn("Abbrechen", "btn ghost", closeSheet), h("button", {type: "submit", class: "btn primary"}, "Speichern")));
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
        toast("Einstellungen gespeichert", [], true);
      }
    });
    openSheet("Einstellungen und Ambiente", [form], false);
  }
