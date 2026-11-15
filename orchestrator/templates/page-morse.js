  const MORSE_EDGE = 0.005;

  function morseSigns(step) {
    return [...(step.joined ? Morse.joined(step.sign) : Morse.words(step.sign)), ...Morse.words(step.text)];
  }

  function keyEdge(param, at, length, level) {
    const edge = Math.min(MORSE_EDGE, length / 4);
    param.setValueAtTime(0, at);
    param.linearRampToValueAtTime(level, at + edge);
    param.setValueAtTime(level, at + length - edge);
    param.linearRampToValueAtTime(0, at + length);
  }

  /**
   * @param {AudioContext} sound the page's audio context.
   * @param {object} item the row that sounds now.
   * @param {object} step the Morse step the radio set planned: sign, joined, text and pitch.
   * @returns {Promise<boolean>} whether the whole message was keyed to its end; false when Stop or a mode change cut it or its tone is silent.
   */
  function keyMorse(sound, item, step) {
    const level = loudness(item.tone);
    const {tones, ms} = Morse.timeline(morseSigns(step), settings.morse.wpm);
    if (level <= 0 || !tones.length) {
      return Promise.resolve(false);
    }
    const source = sound.createOscillator();
    const gain = sound.createGain();
    const start = sound.currentTime;
    const seconds = ms / 1000;
    source.type = "sine";
    source.frequency.value = step.pitch;
    gain.gain.setValueAtTime(0, start);
    tones.forEach(([at, length]) => keyEdge(gain.gain, start + at / 1000, length / 1000, level));
    source.connect(gain).connect(sound.destination);
    voicePace(item, Infinity, seconds);
    const ended = sounded(item, source, seconds);
    source.start(start);
    source.stop(start + seconds);
    return ended.then(() => speech.item === item && !item.cut);
  }

  async function setMorseSpeed(wpm) {
    if (wpm !== settings.morse.wpm && await saveSettings({...settings, space: savedSpace(), morse: {wpm}})) {
      toast("Morse speed saved", [`The radio keys Morse at ${Morse.rate(wpm)}.`], true);
    }
    redrawFilters();
  }

  function morseSpeed() {
    const {wpm} = settings.morse;
    const shown = h("output", {class: "morse-rate"}, Morse.rate(wpm));
    const input = h("input", {type: "range", class: "knob", ...Morse.SPEED, value: wpm, ...named("Morse speed", "Morse speed: words per minute after PARIS, for every browser of this hub"), on: {
      input: (event) => {
        shown.textContent = Morse.rate(Number(event.target.value));
      },
      change: (event) => setMorseSpeed(Number(event.target.value)),
    }});
    return h("label", {class: "morse-speed"}, h("span", {}, "Morse speed"), input, shown);
  }
