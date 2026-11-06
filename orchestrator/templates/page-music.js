  function context() {
    if (!audio) {
      try {
        audio = new window.AudioContext();
      } catch {
        audio = null;
      }
    }
    if (audio && audio.state === "suspended") {
      audio.resume().catch(() => null);
    }
    return audio;
  }

  function glide(param, target, seconds) {
    const now = audio.currentTime;
    param.cancelScheduledValues(now);
    param.setValueAtTime(param.value, now);
    param.linearRampToValueAtTime(target, now + seconds);
  }

  function impulse(sound) {
    const length = sound.sampleRate * 4;
    const buffer = sound.createBuffer(2, length, sound.sampleRate);
    for (let channel = 0; channel < 2; channel += 1) {
      const data = buffer.getChannelData(channel);
      for (let index = 0; index < length; index += 1) {
        data[index] = (Math.random() * 2 - 1) * (1 - index / length) ** 3;
      }
    }
    return buffer;
  }

  function musicLevel() {
    return settings.music.on && !radio.playing ? settings.music.volume * 0.3 * (music.ducked ? DUCK : 1) : 0;
  }

  function note() {
    if (!music.gain) {
      return;
    }
    if (audio.state === "running") {
      const now = audio.currentTime;
      const scale = Math.random() < (music.tension ? 0.3 + 0.5 * music.tension : 0) ? TENSE : CALM;
      const frequency = BASE * 2 * scale[Math.floor(Math.random() * scale.length)] * (Math.random() < 0.3 ? 2 : 1);
      const level = audio.createGain();
      level.gain.setValueAtTime(0, now);
      level.gain.linearRampToValueAtTime(0.07, now + 2.5);
      level.gain.linearRampToValueAtTime(0, now + 8);
      level.connect(music.filter);
      for (const cents of [0, 5]) {
        const oscillator = audio.createOscillator();
        oscillator.type = "triangle";
        oscillator.frequency.value = frequency;
        oscillator.detune.value = cents;
        oscillator.connect(level);
        oscillator.start(now);
        oscillator.stop(now + 8.5);
      }
    }
    const slow = 4500 + Math.random() * 4000;
    const fast = 2400 + Math.random() * 2600;
    music.timer = window.setTimeout(note, slow + (fast - slow) * music.tension);
  }

  function startMusic() {
    const sound = context();
    if (!sound || music.gain) {
      return;
    }
    const gain = sound.createGain();
    gain.gain.value = 0;
    gain.connect(sound.destination);
    const reverb = sound.createConvolver();
    reverb.buffer = impulse(sound);
    reverb.connect(gain);
    const filter = sound.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = 700;
    filter.Q.value = 0.4;
    filter.connect(reverb);
    const dry = sound.createGain();
    dry.gain.value = 0.3;
    filter.connect(dry).connect(gain);
    music.drone = [BASE, BASE * 1.5].map((frequency) => {
      const oscillator = sound.createOscillator();
      const level = sound.createGain();
      const lfo = sound.createOscillator();
      const depth = sound.createGain();
      oscillator.frequency.value = frequency;
      level.gain.value = 0.04;
      lfo.frequency.value = 0.05 + Math.random() * 0.05;
      depth.gain.value = 0.02;
      lfo.connect(depth).connect(level.gain);
      oscillator.connect(level).connect(filter);
      oscillator.start();
      lfo.start();
      return {oscillator, lfo};
    });
    Object.assign(music, {gain, filter});
    note();
  }

  function stopMusic() {
    if (!music.gain) {
      return;
    }
    const {gain, drone} = music;
    window.clearTimeout(music.timer);
    glide(gain.gain, 0, 2);
    music.gain = null;
    window.setTimeout(() => {
      for (const {oscillator, lfo} of drone) {
        oscillator.stop();
        lfo.stop();
      }
      gain.disconnect();
    }, 2500);
  }

  function tuneMusic(seconds) {
    music.tension = Math.min(waitingCount() / 4, 1);
    if (music.gain) {
      glide(music.filter.frequency, 700 + 900 * music.tension, 4);
      glide(music.drone[1].oscillator.detune, 8 * music.tension, 6);
      glide(music.gain.gain, musicLevel(), seconds);
    }
  }

  function syncMusic() {
    if (settings.music.on) {
      startMusic();
    } else {
      stopMusic();
    }
    tuneMusic(FADE / 1000);
  }

  function musicButton() {
    const button = document.getElementById("music-toggle");
    if (!button) {
      return;
    }
    button.setAttribute("aria-pressed", String(settings.music.on));
    button.textContent = settings.music.on ? "♪ Musik an" : "♪ Musik";
  }

  function toggleMusic() {
    context();
    saveSettings({...settings, music: {...settings.music, on: !settings.music.on}});
  }
