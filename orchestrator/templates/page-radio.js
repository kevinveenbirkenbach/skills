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

  function stopStream() {
    radio.element.pause();
    radio.element.removeAttribute("src");
    radio.element.load();
    radio.playing = false;
    tuneMusic(FADE / 1000);
  }

  function syncRadio() {
    const due = Ambience.activeStream(settings.streams, Ambience.slotOf(new Date()));
    const url = due ? due.url : "";
    if (url === radio.url && !radio.waiting) {
      return;
    }
    const origin = url ? new URL(url).origin : "";
    if (origin && !pageMedia.has(origin)) {
      if (state.media.includes(origin)) {
        window.location.reload();
      }
      return;
    }
    radio.url = url;
    radio.waiting = false;
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
        tuneMusic(FADE / 1000);
        fadeRadio(1, () => null);
      }).catch(() => {
        radio.waiting = true;
      });
    });
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
