  function play(kind, volume) {
    const sound = context();
    if (!sound) {
      return;
    }
    const level = Math.max(volume * 0.5, 0.0002);
    duck(Math.max(...TONES[kind].map(([, at, length]) => at + length)));
    for (const [frequency, at, length] of TONES[kind]) {
      const oscillator = sound.createOscillator();
      const gain = sound.createGain();
      const start = sound.currentTime + at;
      oscillator.type = kind === "mayday" ? "square" : "sine";
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(level, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + length);
      oscillator.connect(gain).connect(sound.destination);
      oscillator.start(start);
      oscillator.stop(start + length + 0.05);
    }
  }

  function notifyLabel() {
    const button = document.getElementById("notify");
    if (!button) {
      return;
    }
    const permission = "Notification" in window ? Notification.permission : "unsupported";
    const labels = {granted: "Benachrichtigungen an", denied: "Benachrichtigungen blockiert", default: "Benachrichtigungen aktivieren", unsupported: "Benachrichtigungen fehlen im Browser"};
    relabel(button, "bi-bell", labels[permission] || labels.default);
    button.disabled = permission !== "default";
  }

  async function askNotify() {
    if ("Notification" in window) {
      await Notification.requestPermission();
    }
    notifyLabel();
  }

  function announce() {
    const alarms = new Map(alarmRows().map((row) => [`${row.ts}|${row.from}`, row]));
    const radio = new Set(state.radio.map((row) => `${row.ts}|${row.from}|${row.text.slice(0, 40)}`));
    if (known.inbox !== null && live()) {
      const fresh = state.inbox.filter((item) => !known.inbox.has(keyOf(item)));
      const newAlarms = [...alarms].filter(([key]) => !known.alarms.has(key)).map(([, row]) => row);
      const newRadio = state.radio.filter((row) => !known.radio.has(`${row.ts}|${row.from}|${row.text.slice(0, 40)}`));
      const direct = newRadio.filter((row) => row.to.includes(HUMAN));
      const present = {mayday: newAlarms.length > 0, review: fresh.some((item) => item.kind !== "operator"), direct: direct.length > 0, radio: newRadio.length > 0};
      const kind = SOUND_KINDS.map(([id]) => id).find((id) => present[id] && settings.sounds[id].on);
      if (kind) {
        play(kind, loudness(kind));
      }
      const lead = kind ? Math.max(...TONES[kind].map(([, at, length]) => at + length)) : 0;
      window.setTimeout(() => speakRows(newRadio), lead * 1000);
      if (settings.notify && "Notification" in window && Notification.permission === "granted") {
        for (const row of newAlarms) {
          new Notification(`${row.class === "mayday" ? "Mayday" : "Pan-Pan"} von ${dash(row.from)}`, {body: row.text.slice(0, 200), tag: `alarm-${row.ts}`, requireInteraction: row.class === "mayday"});
        }
        for (const item of fresh) {
          new Notification(`${ITEM_LABELS[item.kind]} wartet`, {body: item.title.slice(0, 200), tag: `item-${keyOf(item)}`, requireInteraction: item.kind === "ask"});
        }
        for (const row of direct) {
          new Notification(`Funk von ${dash(row.from)}`, {body: row.text.slice(0, 200), tag: `direct-${row.ts}`});
        }
      }
    }
    known.inbox = new Set(state.inbox.map(keyOf));
    known.alarms = new Set(alarms.keys());
    known.radio = radio;
    for (const batch of state.pending) {
      if (!known.batches.has(batch.id)) {
        known.batches.add(batch.id);
        const source = batch.source.startsWith("rule:") ? "Regel" : "Freigabe";
        undoToast(batch, `${source}: ${batch.items.map((item) => short(item.title)).join(", ")}`);
      }
    }
  }
