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

  function say(item) {
    speech.pending = Voice.enqueue(speech.pending, item, SPEECH_QUEUE);
    pump();
    drawBubbles();
  }

  function readSilently(item, next) {
    Object.assign(item, {started: performance.now(), duration: Bubbles.reading(item.words.length)});
    speech.current = item;
    speech.timer = window.setTimeout(() => {
      Object.assign(speech, {current: null, timer: 0});
      drawSpeaker();
      next();
    }, item.duration * 1000);
    drawSpeaker();
  }

  function endSilent() {
    window.clearTimeout(speech.timer);
    Object.assign(speech, {current: null, timer: 0, busy: false});
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
        if (speech.source === source) {
          Object.assign(speech, {current: null, source: null});
          drawSpeaker();
        }
        resolve();
      };
      source.addEventListener("ended", ended, {once: true});
      timer = window.setTimeout(() => {
        source.stop();
        ended();
      }, (seconds + SOUND_SLACK) * 1000);
      duck(seconds);
      Object.assign(item, {started: performance.now(), duration: seconds});
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
    const voiced = await transmit(item, audio);
    if (speech.item !== item) {
      next();
      return;
    }
    Object.assign(speech, {current: null, source: null, item: null});
    drawSpeaker();
    if (!voiced && settings.bubbles && item.words) {
      readSilently(item, next);
      return;
    }
    next();
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

  function speakRows(rows) {
    for (const row of rows.filter((entry) => entry.ts >= state.now - SPEECH_FRESH)) {
      const steps = RadioSet.plan(row, radioSet, liveSpeech());
      if (steps.length || (settings.bubbles && Bubbles.picked(row, radioSet))) {
        const line = row.text.split("\n").map((part) => part.trim()).find(Boolean) || "";
        say({row, voice: row.voice, tone: Voice.toneOf(row, HUMAN), cls: row.class, who: row.source, sent: Boolean(RadioSet.ledgerOf(row, state.messages)), line: short(line), words: Bubbles.words(row.text), silent: !steps.length});
      }
    }
  }

  function micGap() {
    return !window.isSecureContext || !navigator.mediaDevices
      ? "The microphone needs a secure context: open the hub via 127.0.0.1 or localhost"
      : !window.MediaRecorder ? "This browser cannot record" : !state.speech.stt ? `Voice input is off: ${state.speech.stt_off}` : "";
  }

  function micButton(field) {
    const button = h("button", {type: "button", class: "btn small ghost icon-only mic", "aria-pressed": "false", ...named("Voice input", "Voice input: hold and speak; the text lands in the field and is not sent")}, icon("bi-mic"));
    const reason = micGap();
    if (reason) {
      button.disabled = true;
      button.title = `Voice input: ${reason}`;
      return button;
    }
    const press = (event) => {
      event.preventDefault();
      record(field, button);
    };
    button.addEventListener("pointerdown", press);
    for (const name of ["pointerup", "pointerleave", "pointercancel"]) {
      button.addEventListener(name, release);
    }
    button.addEventListener("keydown", (event) => {
      if ((event.key === " " || event.key === "Enter") && !event.repeat) {
        press(event);
      }
    });
    button.addEventListener("keyup", (event) => {
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        release();
      }
    });
    return button;
  }

  async function record(field, button) {
    if (mic.held || mic.recorder || mic.busy) {
      return;
    }
    mic.held = true;
    let media = null;
    try {
      media = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
    } catch (error) {
      mic.held = false;
      toast("Microphone not available", [String(error.message || error)], false);
      return;
    }
    if (!mic.held) {
      media.getTracks().forEach((track) => track.stop());
      return;
    }
    const recorder = new MediaRecorder(media);
    const chunks = [];
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) {
        chunks.push(event.data);
      }
    });
    recorder.addEventListener("stop", () => {
      media.getTracks().forEach((track) => track.stop());
      mic.recorder = null;
      button.setAttribute("aria-pressed", "false");
      transcribe(new Blob(chunks, {type: recorder.mimeType}), field, button);
    }, {once: true});
    mic.recorder = recorder;
    recorder.start();
    button.setAttribute("aria-pressed", "true");
    mic.timer = window.setTimeout(release, state.speech.seconds * 1000);
  }

  function release() {
    mic.held = false;
    window.clearTimeout(mic.timer);
    if (mic.recorder && mic.recorder.state === "recording") {
      mic.recorder.stop();
    }
  }

  async function wavOf(blob, sound) {
    const decoded = await sound.decodeAudioData(await blob.arrayBuffer());
    const rate = state.speech.rate;
    const length = Voice.frames(decoded.duration, rate, state.speech.seconds);
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

  async function transcribe(blob, field, button) {
    const sound = context();
    if (!sound || !blob.size) {
      return;
    }
    mic.busy = true;
    button.disabled = true;
    try {
      const result = await send("/api/stt", await wavOf(blob, sound), "audio/wav");
      if (!result.ok || !result.data) {
        throw new Error(`${result.status} ${result.text}`.trim());
      }
      if (result.data.text) {
        field.value = [field.value.trim(), result.data.text].filter(Boolean).join(" ");
        field.dispatchEvent(new Event("input", {bubbles: true}));
      }
      field.focus();
    } catch (error) {
      toast("Voice input failed", [String(error.message || error)], false);
    } finally {
      mic.busy = false;
      button.disabled = false;
    }
  }
