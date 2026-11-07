  const PLAY_REFUSED = {
    NotAllowedError: ["blocked", "Klick nötig", "Der Browser blockiert automatisches Abspielen: ein Klick auf ▶ oder irgendwo auf die Seite startet den Sender."],
    NotSupportedError: ["error", "nicht abspielbar", "Nicht abspielbar: der Browser versteht Format oder Adresse nicht, oder der Sender leitet auf eine Adresse um, von der die Seite keinen Ton laden darf."],
  };
  const MEDIA_ERRORS = {1: "Laden abgebrochen", 2: "Netzwerkfehler", 3: "Ton nicht dekodierbar", 4: "Format oder Adresse nicht abspielbar"};

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

  function radioTrouble(kind, label, note) {
    radioStatus(kind, label, note);
    const key = `${radio.url}|${kind}|${label}`;
    if (radio.told !== key) {
      radio.told = key;
      const stream = settings.streams[radio.index];
      toast(`Radio ${kind === "blocked" ? "blockiert" : "stumm"}: ${stream ? stream.name : radio.url}`, [note], false);
    }
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
    const url = index < 0 ? "" : settings.streams[index].url;
    if (url === radio.url && !radio.waiting) {
      drawStations();
      return;
    }
    const origin = url ? new URL(url).origin : "";
    radio.index = index;
    if (origin && !pageMedia.has(origin)) {
      radioStatus("reload", "lädt neu", "Neue Adresse: die Seite lädt neu, damit der Browser von dort Ton laden darf.");
      if (state.media.includes(origin)) {
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
        radio.told = "";
        radioStatus("playing", "spielt", `spielt seit ${clock.format(new Date())}`);
        tuneMusic(FADE / 1000);
        fadeRadio(1, () => null);
      }).catch((error) => {
        if (radio.url !== url || error.name === "AbortError") {
          return;
        }
        radio.waiting = true;
        const [kind, label, note] = PLAY_REFUSED[error.name] || ["error", "Fehler", `${error.name}: ${error.message}`];
        // Trip-wire: the media error event fires before this rejection and already named the cause; a second toast would hide it.
        if (!(kind === "error" && radio.state === "error")) {
          radioTrouble(kind, label, note);
        }
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
      radioTrouble("error", "Fehler", `Der Sender spielt nicht: ${reason}${failure && failure.message ? ` (${failure.message})` : ""}.`);
    });
    document.addEventListener("securitypolicyviolation", (event) => {
      if (event.effectiveDirective === "media-src" && radio.url && !event.blockedURI.startsWith(window.location.origin)) {
        radioTrouble("error", "gesperrt", `Der Sender leitet auf ${event.blockedURI} um; die Seite spielt nur von den Adressen, die du mit deinem Passkey gespeichert hast.`);
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
