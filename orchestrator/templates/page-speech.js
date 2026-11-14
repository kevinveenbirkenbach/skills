  function tones() {
    return {sounds: radioSet.sounds, squelch: radioSet.squelch, music: settings.music};
  }

  function loudness(kind) {
    return Voice.loudness(kind, tones());
  }

  function keepRadio(change) {
    const before = radioSet.mode;
    radioSet = RadioSet.valid({...radioSet, ...change});
    keep(RadioSet.KEY, radioSet);
    hush(before !== radioSet.mode);
    drawRadioSet();
  }

  function hush(switched) {
    const {item, source} = speech;
    if (source && item && item.row && !allows(rendered(item, item.at), item.playing)) {
      item.cut = true;
      source.stop();
    }
    if (switched && radioSet.mode === "silence") {
      silenceBeeps();
    }
  }

  /**
   * @param {object|undefined} step the step the radio set plans now at the index that plays.
   * @param {string} kind word, speech or burst: what plays or is about to play there.
   * @returns {boolean} whether that sound may play: the planned kind, or the burst standing in for a planned speech line.
   */
  function allows(step, kind) {
    return Boolean(step) && (step.kind === kind || (kind === "burst" && step.kind === "speech"));
  }

  function speechFailed(lines) {
    if (Date.now() - speech.warned > SPEECH_QUIET) {
      speech.warned = Date.now();
      toast("Reading radio aloud failed", lines, false);
    }
  }

  /**
   * @param {...object} items the rows to read aloud.
   */
  function say(...items) {
    speech.pending = items.reduce((pending, item) => Voice.enqueue(pending, item, SPEECH_QUEUE), speech.pending);
    pump();
    drawBubbles();
  }

  /**
   * @param {object} item the row that sounds now.
   * @param {number} span how many of its unread words this sound says: Infinity for the spoken rest, 0 for a procedure word.
   * @param {number} seconds how long the sound plays.
   */
  function voicePace(item, span, seconds) {
    const floor = wordsRead(item);
    Object.assign(item, {floor, span: Math.min(span, saidOf(item).length - floor), started: performance.now(), duration: seconds, reading: false});
  }

  function readingPace(item) {
    if (!item.reading) {
      const floor = wordsRead(item);
      const span = item.words.length - floor;
      Object.assign(item, {floor, span, started: performance.now(), duration: Bubbles.reading(span), reading: true});
    }
  }

  function readSilently(item, next) {
    readingPace(item);
    speech.current = item;
    speech.timer = window.setTimeout(() => {
      Object.assign(speech, {current: null, timer: 0, item: null});
      try {
        drawSpeaker();
      } finally {
        next();
      }
    }, Math.max(0, item.started + item.duration * 1000 - performance.now()));
    drawSpeaker();
  }

  function endSilent() {
    window.clearTimeout(speech.timer);
    Object.assign(speech, {current: null, timer: 0, busy: false, item: null});
  }

  function dropSilent() {
    speech.pending = speech.pending.filter((item) => !item.silent);
    if (speech.timer) {
      endSilent();
      drawSpeaker();
      pump();
    }
  }

  function sounded(item, source, seconds) {
    return new Promise((resolve) => {
      let timer = 0;
      const ended = () => {
        window.clearTimeout(timer);
        try {
          if (speech.source === source) {
            Object.assign(speech, {current: null, source: null});
            drawSpeaker();
          }
        } finally {
          resolve();
        }
      };
      source.addEventListener("ended", ended, {once: true});
      timer = window.setTimeout(() => {
        source.stop();
        ended();
      }, (seconds + SOUND_SLACK) * 1000);
      duck(seconds);
      Object.assign(speech, {current: item, source});
      drawSpeaker();
    });
  }

  function burst(sound, item) {
    const shape = RadioSet.burst(loudness(item.tone));
    if (shape.gain <= 0) {
      return Promise.resolve();
    }
    const frames = Math.ceil(sound.sampleRate * shape.seconds);
    const buffer = sound.createBuffer(1, frames, sound.sampleRate);
    const data = buffer.getChannelData(0);
    for (let index = 0; index < frames; index += 1) {
      data[index] = Math.random() * 2 - 1;
    }
    const source = sound.createBufferSource();
    const filter = sound.createBiquadFilter();
    const gain = sound.createGain();
    const start = sound.currentTime;
    filter.type = "bandpass";
    filter.frequency.value = shape.frequency;
    filter.Q.value = shape.q;
    gain.gain.setValueAtTime(shape.gain, start);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + shape.seconds);
    source.buffer = buffer;
    source.connect(filter).connect(gain).connect(sound.destination);
    if (item.words) {
      readingPace(item);
    } else {
      voicePace(item, Infinity, shape.seconds);
    }
    const ended = sounded(item, source, shape.seconds);
    source.start(start);
    source.stop(start + shape.seconds);
    return ended;
  }

  async function spoken(sound, item, step, done) {
    speech.loading = item;
    drawBubbles();
    try {
      const response = await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: step.text, voice: item.voice}), cache: "no-store"});
      const held = response.status === 503 && (response.headers.get("Content-Type") || "").startsWith("application/json");
      if (!response.ok) {
        return held ? "held" : `${response.status} ${(await response.text()).trim()}`;
      }
      const buffer = await sound.decodeAudioData(await response.arrayBuffer());
      if (speech.item !== item) {
        return "";
      }
      if (!allows(rendered(item, done), step.kind)) {
        return "dropped";
      }
      const source = sound.createBufferSource();
      const gain = sound.createGain();
      gain.gain.value = loudness(item.tone);
      source.buffer = buffer;
      source.connect(gain).connect(sound.destination);
      voicePace(item, step.kind === "speech" ? Infinity : 0, buffer.duration);
      const ended = sounded(item, source, buffer.duration);
      source.start();
      await ended;
      return speech.item === item && item.cut ? "dropped" : "";
    } catch (error) {
      return String(error.message || error);
    } finally {
      if (speech.loading === item) {
        speech.loading = null;
      }
    }
  }

  function liveSpeech() {
    return {tts: state.speech.tts, open: state.speech.gate.open};
  }

  function stepOf(item, done, live) {
    return (item.row ? RadioSet.plan(item.row, radioSet, live || liveSpeech()) : item.steps)[done];
  }

  function rendered(item, done) {
    return item.row ? stepOf(item, done, {...liveSpeech(), open: true}) : item.steps[done];
  }

  async function transmit(item, audio) {
    let voiced = false;
    for (let done = 0; ; done += 1) {
      const step = stepOf(item, done);
      if (!step || speech.item !== item) {
        return voiced;
      }
      Object.assign(item, {at: done, playing: step.kind, cut: false});
      if (step.kind === "burst") {
        await burst(audio, item);
        continue;
      }
      const failed = await spoken(audio, item, step, done);
      if (failed === "dropped") {
        done -= 1;
        continue;
      }
      voiced = voiced || (!failed && step.kind === "speech");
      if (failed && failed !== "held") {
        speechFailed([failed]);
      }
      if (failed && step.kind === "speech" && speech.item === item && allows(stepOf(item, done), "burst")) {
        item.playing = "burst";
        await burst(audio, item);
      }
    }
  }

  async function pump() {
    if (speech.busy || !speech.pending.length) {
      return;
    }
    const [item, ...rest] = speech.pending;
    const audio = item.silent ? null : context();
    if (!item.silent && !audio) {
      speech.pending = [];
      return;
    }
    Object.assign(speech, {pending: rest, busy: true, item});
    const next = () => {
      speech.busy = false;
      pump();
    };
    if (item.silent) {
      readSilently(item, next);
      return;
    }
    let voiced = false;
    try {
      voiced = await transmit(item, audio);
    } catch (error) {
      speechFailed([String(error.message || error)]);
    }
    if (speech.item !== item) {
      next();
      return;
    }
    Object.assign(speech, {current: null, source: null, item: null});
    if (!voiced && settings.bubbles && item.words) {
      readSilently(item, next);
      return;
    }
    try {
      drawSpeaker();
    } finally {
      next();
    }
  }

  function cancelSpeech() {
    if (speech.timer) {
      endSilent();
    }
    const playing = speech.source;
    Object.assign(speech, {pending: [], current: null, loading: null, source: null, item: null});
    if (playing) {
      playing.stop();
    }
    clearBubbles();
    drawSpeaker();
  }

  /**
   * @param {Array<object>} rows the radio rows the page has not announced yet.
   * @param {boolean} arrived whether they arrived while the page polled without a gap.
   */
  function speakRows(rows, arrived) {
    const [spoken, quiet] = [[], []];
    for (const row of rows) {
      const fresh = row.ts >= state.now - SPEECH_FRESH;
      const steps = fresh && settings.channels.aloud ? RadioSet.plan(row, radioSet, liveSpeech()) : [];
      const line = short(row.text.split("\n").map((part) => part.trim()).find(Boolean) || "");
      if (fresh && (steps.length || (settings.bubbles && Bubbles.picked(row, radioSet)))) {
        spoken.push({row, voice: row.voice, tone: Voice.toneOf(row, HUMAN), cls: row.class, who: row.source, sent: Boolean(RadioSet.ledgerOf(row, state.messages)), line, words: Bubbles.words(row.text), silent: !steps.length});
      } else if (settings.bubbles && arrived && row.ts >= state.now - LIVE_GAP) {
        quiet.push({who: row.source, cls: row.class, line, words: Bubbles.words(line), quiet: true});
      }
    }
    quietBubbles(quiet);
    say(...spoken);
  }

  function micGap() {
    return !window.isSecureContext || !navigator.mediaDevices
      ? "The microphone needs a secure context: open the hub via 127.0.0.1 or localhost"
      : !window.MediaRecorder ? "This browser cannot record" : !state.speech.stt ? `Voice input is off: ${state.speech.stt_off}` : "";
  }

  async function wavOf(blob, sound, seconds) {
    const decoded = await sound.decodeAudioData(await blob.arrayBuffer());
    const rate = state.speech.rate;
    const length = Voice.frames(decoded.duration, rate, seconds);
    if (length < rate / 4) {
      throw new Error("too short: speak for at least a quarter second");
    }
    const offline = new OfflineAudioContext(1, length, rate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return Voice.wav(rendered.getChannelData(0), rate);
  }
