  function loudness(kind) {
    return Voice.loudness(kind, settings);
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

  async function pump() {
    if (speech.busy || !speech.pending.length) {
      return;
    }
    const [item, ...rest] = speech.pending;
    const sound = item.silent ? null : context();
    if (!item.silent && !sound) {
      speech.pending = [];
      return;
    }
    speech.pending = rest;
    speech.busy = true;
    const next = () => {
      speech.busy = false;
      pump();
    };
    if (item.silent) {
      readSilently(item, next);
      return;
    }
    speech.loading = item;
    drawBubbles();
    try {
      const response = await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: item.text, voice: item.voice}), cache: "no-store"});
      if (!response.ok) {
        throw new Error(`${response.status} ${(await response.text()).trim()}`);
      }
      const buffer = await sound.decodeAudioData(await response.arrayBuffer());
      if (speech.loading !== item) {
        next();
        return;
      }
      const source = sound.createBufferSource();
      const gain = sound.createGain();
      gain.gain.value = loudness(item.tone);
      source.buffer = buffer;
      source.connect(gain).connect(sound.destination);
      source.addEventListener("ended", () => {
        Object.assign(speech, {current: null, source: null});
        drawSpeaker();
        next();
      }, {once: true});
      duck(buffer.duration);
      Object.assign(item, {started: performance.now(), duration: buffer.duration});
      Object.assign(speech, {current: item, source, loading: null});
      drawSpeaker();
      source.start();
    } catch (error) {
      const kept = speech.loading === item;
      speech.loading = null;
      speechFailed([String(error.message || error)]);
      if (kept && settings.bubbles && item.words) {
        readSilently(item, next);
        return;
      }
      next();
    }
  }

  function cancelSpeech() {
    if (speech.timer) {
      endSilent();
    }
    Object.assign(speech, {pending: [], current: null, loading: null});
    if (speech.source) {
      speech.source.stop();
    }
    clearBubbles();
    drawSpeaker();
  }

  function speakRows(rows) {
    const voiced = settings.speech.on && state.speech.tts;
    if (!voiced && !settings.bubbles) {
      return;
    }
    for (const row of rows.filter((entry) => entry.ts >= state.now - SPEECH_FRESH)) {
      const audible = voiced && Voice.speakable(row, settings.speech);
      if (audible || (settings.bubbles && Bubbles.picked(row, settings.speech))) {
        const line = row.text.split("\n").map((part) => part.trim()).find(Boolean) || "";
        say({text: row.speech, voice: row.voice, tone: Voice.toneOf(row, HUMAN), cls: row.class, who: row.source, line: short(line), words: Bubbles.words(row.text), silent: !audible});
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
