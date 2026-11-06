  function loudness(kind) {
    return Voice.loudness(kind, settings);
  }

  function speechFailed(lines) {
    if (Date.now() - speech.warned > SPEECH_QUIET) {
      speech.warned = Date.now();
      toast("Funk vorlesen fehlgeschlagen", lines, false);
    }
  }

  function say(item) {
    speech.pending = Voice.enqueue(speech.pending, item, SPEECH_QUEUE);
    pump();
  }

  async function pump() {
    if (speech.busy || !speech.pending.length) {
      return;
    }
    const sound = context();
    if (!sound) {
      speech.pending = [];
      return;
    }
    const [item, ...rest] = speech.pending;
    speech.pending = rest;
    speech.busy = true;
    const next = () => {
      speech.busy = false;
      pump();
    };
    try {
      const response = await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Hub": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: item.text, voice: item.voice}), cache: "no-store"});
      if (!response.ok) {
        throw new Error(`${response.status} ${(await response.text()).trim()}`);
      }
      const buffer = await sound.decodeAudioData(await response.arrayBuffer());
      const source = sound.createBufferSource();
      const gain = sound.createGain();
      gain.gain.value = loudness(item.tone);
      source.buffer = buffer;
      source.connect(gain).connect(sound.destination);
      source.addEventListener("ended", next, {once: true});
      duck(buffer.duration);
      source.start();
    } catch (error) {
      speechFailed([String(error.message || error)]);
      next();
    }
  }

  function speakRows(rows) {
    if (!settings.speech.on || !state.speech.tts) {
      return;
    }
    for (const row of rows.filter((entry) => entry.ts >= state.now - SPEECH_FRESH && Voice.speakable(entry, settings.speech))) {
      say({text: row.speech, voice: row.voice, tone: Voice.toneOf(row, HUMAN), cls: row.class});
    }
  }

  function micButton(field) {
    const button = h("button", {type: "button", class: "btn small ghost icon-btn mic", "aria-pressed": "false", "aria-label": "Spracheingabe: gedrückt halten und sprechen", title: "Gedrückt halten und sprechen; der Text landet im Feld und wird nicht gesendet"}, "🎙");
    const reason = !window.isSecureContext || !navigator.mediaDevices
      ? "Das Mikrofon braucht einen sicheren Kontext: öffne den Hub über 127.0.0.1 oder localhost"
      : !window.MediaRecorder ? "Dieser Browser kann nicht aufnehmen" : !state.speech.stt ? "Spracheingabe ist aus: whisper.cpp oder sein Modell fehlt im Image" : "";
    if (reason) {
      button.disabled = true;
      button.title = reason;
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
      toast("Mikrofon nicht verfügbar", [String(error.message || error)], false);
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

  async function transcribe(blob, field, button) {
    const sound = context();
    if (!sound || !blob.size) {
      return;
    }
    mic.busy = true;
    button.disabled = true;
    try {
      const decoded = await sound.decodeAudioData(await blob.arrayBuffer());
      const rate = state.speech.rate;
      const length = Voice.frames(decoded.duration, rate, state.speech.seconds);
      if (length < rate / 4) {
        throw new Error("zu kurz: halte die Taste, solange du sprichst");
      }
      const offline = new OfflineAudioContext(1, length, rate);
      const source = offline.createBufferSource();
      source.buffer = decoded;
      source.connect(offline.destination);
      source.start();
      const rendered = await offline.startRendering();
      const result = await send("/api/stt", Voice.wav(rendered.getChannelData(0), rate), "audio/wav");
      if (!result.ok || !result.data) {
        throw new Error(`${result.status} ${result.text}`.trim());
      }
      if (result.data.text) {
        field.value = [field.value.trim(), result.data.text].filter(Boolean).join(" ");
        field.dispatchEvent(new Event("input", {bubbles: true}));
      }
      field.focus();
    } catch (error) {
      toast("Spracheingabe fehlgeschlagen", [String(error.message || error)], false);
    } finally {
      mic.busy = false;
      button.disabled = false;
    }
  }
