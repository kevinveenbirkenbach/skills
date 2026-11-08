  const PLAY_REFUSED = {
    NotAllowedError: ["blocked", "Klick nötig", "Der Browser blockiert automatisches Abspielen: ein Klick auf ▶ oder irgendwo auf die Seite startet den Sender."],
    NotSupportedError: ["error", "nicht abspielbar", "Nicht abspielbar: der Browser versteht Format oder Adresse nicht, oder der Sender leitet auf eine Adresse um, von der die Seite keinen Ton laden darf."],
  };
  const MEDIA_ERRORS = {1: "Laden abgebrochen", 2: "Netzwerkfehler", 3: "Ton nicht dekodierbar", 4: "Format oder Adresse nicht abspielbar"};
  const RESOLVE_STEP = "Radio → Sender bearbeiten: ändere die Adresse des Senders, oder entferne ihn, speichere, lege ihn neu an und speichere wieder; dann löst der Server die Weiterleitung neu auf und gibt ihr Ziel frei.";

  function radioVolume() {
    if (radio.element) {
      radio.element.volume = Math.min(Math.max(radio.level * settings.music.volume * (music.ducked ? DUCK : 1), 0), 1);
    }
  }

  function fadeRadio(target, done) {
    window.clearInterval(radio.timer);
    if (radio.level === target) {
      done();
      return;
    }
    const from = radio.level;
    const began = performance.now();
    radio.timer = window.setInterval(() => {
      const progress = Math.min((performance.now() - began) / FADE, 1);
      radio.level = from + (target - from) * progress;
      radioVolume();
      if (progress >= 1) {
        window.clearInterval(radio.timer);
        done();
      }
    }, 100);
  }

  function radioStatus(kind, label, note) {
    Object.assign(radio, {state: kind, short: label, note});
    drawStations();
  }

  function radioTrouble(kind, label, note, cause) {
    const told = radio.told;
    const fresh = Ambience.retold(told, radio.url, kind, cause);
    if (!fresh) {
      radioStatus(...told.status);
      return;
    }
    radioStatus(kind, label, note);
    if (told) {
      told.box.remove();
    }
    const stream = settings.streams[radio.index];
    const box = toast(`Radio ${kind === "blocked" ? "blockiert" : "stumm"}: ${stream ? stream.name : radio.url}`, [note], false);
    radio.told = {...fresh, status: [kind, label, note], box};
  }

  function redirectNote(stream) {
    if (stream && stream.via === null) {
      return "Der Server hat die Weiterleitung dieses Senders noch nicht aufgelöst; ein Speichern nach zehn Minuten versucht es erneut.";
    }
    const released = stream ? stream.via : [];
    const unloaded = released.filter((origin) => !pageMedia.has(origin));
    if (unloaded.length) {
      return `Der Sender leitet auf ${unloaded.join(", ")} um; die geladene Seite darf von dort noch keinen Ton laden: Seite neu laden.`;
    }
    return released.length
      ? `Der Sender leitet auf eine Adresse außerhalb der freigegebenen ${released.join(", ")} um. ${RESOLVE_STEP}`
      : `Der Sender leitet auf eine Adresse um, die noch nicht freigegeben ist; der Browser nennt das Ziel einer Weiterleitung nicht. ${RESOLVE_STEP}`;
  }

  function stopStream() {
    radio.element.pause();
    radio.element.removeAttribute("src");
    radio.element.load();
    radio.playing = false;
    tuneMusic(FADE / 1000);
  }

  function dueStation() {
    const sig = JSON.stringify(settings.streams);
    if (sig !== radio.sig) {
      radio.sig = sig;
      radio.pick = null;
    }
    if (radio.pick === -1) {
      return -1;
    }
    if (radio.pick !== null && settings.streams[radio.pick]) {
      return radio.pick;
    }
    const due = Ambience.activeStream(settings.streams, Ambience.slotOf(new Date()));
    return due ? settings.streams.indexOf(due) : -1;
  }

  function syncRadio() {
    const index = dueStation();
    const stream = index < 0 ? null : settings.streams[index];
    const url = stream ? stream.url : "";
    if (url === radio.url && !radio.waiting) {
      drawStations();
      return;
    }
    const missing = stream ? Ambience.stationOrigins(stream).filter((origin) => !pageMedia.has(origin)) : [];
    radio.index = index;
    if (missing.length) {
      radioStatus("reload", "lädt neu", `Neue Adresse ${missing.join(", ")}: die Seite lädt neu, damit der Browser von dort Ton laden darf.`);
      if (missing.every((origin) => state.media.includes(origin))) {
        window.location.reload();
      }
      return;
    }
    radio.url = url;
    radio.waiting = false;
    radioStatus(url ? "loading" : "", url ? "verbindet" : "", url ? "Verbindet mit dem Sender …" : "");
    fadeRadio(0, () => {
      if (radio.url !== url) {
        return;
      }
      if (!url) {
        stopStream();
        return;
      }
      radio.element.src = url;
      radio.element.play().then(() => {
        radio.playing = true;
        radio.told = null;
        radioStatus("playing", "spielt", `spielt seit ${clock.format(new Date())}`);
        tuneMusic(FADE / 1000);
        fadeRadio(1, () => null);
      }).catch((error) => {
        if (radio.url !== url || error.name === "AbortError") {
          return;
        }
        radio.waiting = true;
        const [kind, label, note] = PLAY_REFUSED[error.name] || ["error", "Fehler", `${error.name}: ${error.message}`];
        radioTrouble(kind, label, note, "refused");
      });
    });
  }

  function playStation(index) {
    const stream = settings.streams[index];
    radio.pick = index;
    if (!(radio.playing && radio.url === stream.url)) {
      radio.waiting = true;
    }
    syncRadio();
  }

  function stopStation() {
    radio.pick = -1;
    syncRadio();
  }

  function radioElement() {
    const element = h("audio", {preload: "none"});
    element.addEventListener("error", () => {
      if (!element.getAttribute("src")) {
        return;
      }
      const failure = element.error;
      radio.playing = false;
      radio.waiting = true;
      tuneMusic(FADE / 1000);
      const reason = failure ? MEDIA_ERRORS[failure.code] || `Fehler ${failure.code}` : "unbekannter Fehler";
      radioTrouble("error", "Fehler", `Der Sender spielt nicht: ${reason}${failure && failure.message ? ` (${failure.message})` : ""}.`, "media");
    });
    document.addEventListener("securitypolicyviolation", (event) => {
      // Trip-wire: for a redirected load, blockedURI is the station's own URL, never the redirect target.
      if (event.effectiveDirective === "media-src" && radio.url && !event.blockedURI.startsWith(window.location.origin)) {
        radioTrouble("error", "gesperrt", redirectNote(settings.streams[radio.index]), "csp");
      }
    });
    return element;
  }

  function duck(seconds) {
    music.ducked += 1;
    tuneMusic(0.15);
    radioVolume();
    window.setTimeout(() => {
      music.ducked -= 1;
      tuneMusic(1.5);
      radioVolume();
    }, (seconds + 0.6) * 1000);
  }

  function unlock() {
    if (settings.music.on) {
      context();
    }
    if (radio.waiting) {
      syncRadio();
    }
  }
