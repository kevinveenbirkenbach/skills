  const PLAY_REFUSED = {
    NotAllowedError: ["blocked", "Click needed", "The browser blocks autoplay: a click on ▶ or anywhere on the page starts the station."],
    NotSupportedError: ["error", "not playable", "Not playable: the browser does not understand the format or the address, or the station redirects to an address the page may not load sound from."],
  };
  const MEDIA_ERRORS = {1: "Loading aborted", 2: "Network error", 3: "Sound not decodable", 4: "Format or address not playable"};
  const RESOLVE_STEP = "Radio → Edit stations: change the station's address, or remove it, save, add it again and save once more; then the server resolves the redirect again and releases its target.";

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
    const box = toast(`Radio ${kind === "blocked" ? "blocked" : "silent"}: ${stream ? stream.name : radio.url}`, [note], false);
    radio.told = {...fresh, status: [kind, label, note], box};
  }

  function redirectNote(stream) {
    if (stream && stream.via === null) {
      return "The server has not resolved this station's redirect yet; saving after ten minutes tries again.";
    }
    const released = stream ? stream.via : [];
    const unloaded = released.filter((origin) => !pageMedia.has(origin));
    if (unloaded.length) {
      return `The station redirects to ${unloaded.join(", ")}; the loaded page may not load sound from there yet: reload the page.`;
    }
    return released.length
      ? `The station redirects to an address outside the released ${released.join(", ")}. ${RESOLVE_STEP}`
      : `The station redirects to an address that is not released yet; the browser does not name the target of a redirect. ${RESOLVE_STEP}`;
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
      radioStatus("reload", "reloading", `New address ${missing.join(", ")}: the page reloads so the browser may load sound from there.`);
      if (missing.every((origin) => state.media.includes(origin))) {
        window.location.reload();
      }
      return;
    }
    radio.url = url;
    radio.waiting = false;
    radioStatus(url ? "loading" : "", url ? "connecting" : "", url ? "Connecting to the station …" : "");
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
        radioStatus("playing", "playing", `playing since ${clock.format(new Date())}`);
        tuneMusic(FADE / 1000);
        fadeRadio(1, () => null);
      }).catch((error) => {
        if (radio.url !== url || error.name === "AbortError") {
          return;
        }
        radio.waiting = true;
        const [kind, label, note] = PLAY_REFUSED[error.name] || ["error", "Error", `${error.name}: ${error.message}`];
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
      const reason = failure ? MEDIA_ERRORS[failure.code] || `Error ${failure.code}` : "unknown error";
      radioTrouble("error", "Error", `The station does not play: ${reason}${failure && failure.message ? ` (${failure.message})` : ""}.`, "media");
    });
    document.addEventListener("securitypolicyviolation", (event) => {
      // Trip-wire: for a redirected load, blockedURI is the station's own URL, never the redirect target.
      if (event.effectiveDirective === "media-src" && radio.url && !event.blockedURI.startsWith(window.location.origin)) {
        radioTrouble("error", "blocked", redirectNote(settings.streams[radio.index]), "csp");
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
